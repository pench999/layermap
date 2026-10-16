import copy
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml
from fastapi.testclient import TestClient
from generate_diagram import render
from network_model import load_model, ModelError, MAX_YAML_BYTES
from view_model import MAX_HTTP_BYTES
from web_app import app


class WebTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.source = Path(__file__).with_name('lan-sample.yaml').read_text(encoding='utf-8')

    def request(self, source=None, **options):
        return self.client.post('/api/render', json={'yaml_text': self.source if source is None else source, **options})

    def test_sample_and_health(self):
        self.assertEqual(self.client.get('/api/health').json()['status'],'ok')
        self.assertEqual(self.client.get('/api/sample').json()['yaml_text'],self.source)

    def test_render_and_device_metadata(self):
        response = self.request()
        self.assertEqual(response.status_code,200,response.text)
        data = response.json()
        ET.fromstring(data['svg'])
        self.assertEqual(data['counts'], {'devices':4,'links':3,'vlans':2})
        self.assertIn('data-element-id="pc-a.ip"',data['svg'])
        self.assertIn('data-binding="l3_to_l2"',data['svg'])
        self.assertIn('DEMO-SW-0001',data['svg'])
        self.assertEqual(response.headers['cache-control'],'no-store')

    def test_single_layer_layout_and_no_bindings(self):
        full = self.request().json()['svg']
        root_full = ET.fromstring(full)
        for layer in ['l1','l2','l3']:
            svg = self.request(view=layer).json()['svg']
            root = ET.fromstring(svg)
            self.assertLess(float(root.attrib['height']), float(root_full.attrib['height']))
            self.assertEqual([g.attrib['data-layer'] for g in root.iter() if 'data-layer' in g.attrib],[layer])
            self.assertNotIn('data-binding=',svg)
        self.assertNotIn('data-binding=', self.request(show_bindings=False).json()['svg'])

    def test_semantic_error_has_path_and_source_position(self):
        invalid = self.source.replace('l3_interface: pc-a.ip, l2_interface: pc-a.l2, vlan: vlan-office',
                                      'l3_interface: pc-a.ip, l2_interface: pc-a.l2, vlan: vlan-guest')
        response = self.request(invalid)
        self.assertEqual(response.status_code,422,response.text)
        issue = response.json()['errors'][0]
        self.assertEqual(issue['path'],'bindings.l3_to_l2[0].vlan')
        self.assertGreater(issue['line'],1)
        self.assertGreater(issue['column'],1)
        self.assertNotIn('svg',response.json())

    def test_yaml_syntax_error_has_position(self):
        issue = self.request('devices: [').json()['errors'][0]
        self.assertIsNotNone(issue['line'])

    def test_wrong_types_missing_fields_and_invalid_ip_are_422(self):
        for text in ['null','[]','schema: lan-example/v1',self.source.replace('192.168.10.10/24','not-an-ip')]:
            self.assertEqual(self.request(text).status_code,422)

    def test_limits_duplicates_and_aliases(self):
        for text in ['x'*(MAX_YAML_BYTES+1),'schema: a\nschema: b', 'x: &a [1,2]\ny: *a']:
            self.assertEqual(self.request(text).status_code,422)
        response = self.client.post('/api/render',content=b'x'*(MAX_HTTP_BYTES+1),headers={'Content-Type':'application/json'})
        self.assertEqual(response.status_code,413)

    def test_unknown_fields_and_views_rejected_without_input_echo(self):
        result = self.request(view='unknown')
        self.assertEqual(result.status_code,422)
        self.assertNotIn('yaml_text', result.text)
        m = yaml.safe_load(self.source)
        m['devices'][0]['unknown_secret'] = 'DO-NOT-ECHO'
        result = self.request(yaml.safe_dump(m,allow_unicode=True))
        self.assertEqual(result.status_code,422)
        self.assertNotIn('DO-NOT-ECHO',result.text)

    def test_svg_escapes_text_and_device_attributes(self):
        m = yaml.safe_load(self.source)
        old = m['devices'][0]['id']
        evil = 'pc-" onclick="alert(1)'
        m['devices'][0]['id'] = evil
        for section,group in [('l1','ports'),('l2','interfaces'),('l3','interfaces')]:
            for item in m[section][group]:
                if item['device']==old:item['device']=evil
        for r in m['l3']['routes']:
            if r['device']==old:r['device']=evil
        m['name']='<script>alert(1)</script>'
        svg = self.request(yaml.safe_dump(m,allow_unicode=True)).json()['svg']
        root = ET.fromstring(svg)
        self.assertNotIn('<script>',svg)
        self.assertFalse(any('onclick' in element.attrib for element in root.iter()))
        self.assertTrue(any(e.attrib.get('data-device')==evil for e in root.iter()))

    def test_bundled_sample_catalog_and_rendering(self):
        catalog = self.client.get('/api/samples').json()['samples']
        self.assertEqual([s['id'] for s in catalog], ['base','add-pc','add-vlan','multi-site','connection-status'])
        expected = {'base':(4,3,2), 'add-pc':(5,4,2), 'add-vlan':(5,4,3), 'multi-site':(36,33,6), 'connection-status':(10,9,2)}
        for item in catalog:
            self.assertNotIn('file',item)
            response = self.client.get('/api/samples/'+item['id'])
            self.assertEqual(response.status_code,200)
            sample = response.json()
            self.assertEqual(sample['filename'],item['filename'])
            rendered = self.request(sample['yaml_text'])
            self.assertEqual(rendered.status_code,200,rendered.text)
            counts = rendered.json()['counts']
            self.assertEqual((counts['devices'],counts['links'],counts['vlans']),expected[item['id']])
            if item['id']=='multi-site':
                self.assertEqual(rendered.json()['display']['status'],'too_large')
                self.assertEqual(rendered.json()['svg'],'')
            else:
                ET.fromstring(rendered.json()['svg'])

    def test_sample_id_is_allowlisted(self):
        for sample_id in ['missing','.env','web_app.py']:
            self.assertEqual(self.client.get('/api/samples/'+sample_id).status_code,404)



    def test_multi_site_sample_filters_and_overlapping_groups(self):
        source=self.client.get('/api/samples/multi-site').json()['yaml_text']
        model=load_model(source)
        self.assertEqual(len(model['devices']),36)
        for scope,count in [({'site':'本社'},12),({'site':'大阪支社'},12),({'site':'福岡支社'},12),
                            ({'group':'ネットワーク機器'},9),({'group':'業務端末'},18),({'group':'来客端末'},9),
                            ({'site':'本社','group':'業務端末'},6),({'site':'本社','group':'フロアA'},6),
                            ({'site':'本社','group':'ネットワーク機器'},3)]:
            response=self.request(source,scope=scope)
            self.assertEqual(response.status_code,200,response.text)
            data=response.json()
            self.assertEqual(data['display']['status'],'ready',data['display'])
            self.assertEqual(data['display']['counts']['devices'],count)
            self.assertEqual(data['counts']['devices'],36)
            ET.fromstring(data['svg'])
        data=self.request(source,scope={'site':'本社','group':'業務端末'}).json()
        self.assertEqual(data['display']['boundary_links']['total'],6)
        self.assertEqual(set(data['catalog']['sites']),{'本社','大阪支社','福岡支社'})
        self.assertIn('フロアA',data['catalog']['groups'])
        by_id={d['id']:d for d in model['devices']}
        self.assertEqual(by_id['hq-pc01']['groups'],['業務端末','フロアA'])


if __name__ == '__main__':
    unittest.main()
