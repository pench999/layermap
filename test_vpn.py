import copy
import unittest
from pathlib import Path
import yaml
from fastapi.testclient import TestClient
from web_app import app, render_slots
from vpn_model import VpnRequest,preview_vpn
from network_model import load_model,validate,ModelError
from view_model import ViewScope,prepare_view,display_stats,element_count
from generate_diagram import render
from merge_model import MergeRequest,merge_preview

ROOT=Path(__file__).parent
class VpnTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app)
        self.sample=self.client.get('/api/vpn/sample').json()
        self.base=self.sample['yaml_text'];self.doc=yaml.safe_load(self.sample['connections_yaml'])
    def compose(self,doc=None,base=None):
        return preview_vpn(VpnRequest(yaml_text=base or self.base,connections_yaml=yaml.safe_dump(doc or self.doc,allow_unicode=True)))
    def test_both_modes_roundtrip_no_fake_ports_and_comments_preserved(self):
        base='# preserved comment\r\n'+self.base.replace('\n','\r\n')
        p=self.compose(base=base);model,ix=load_model(p['yaml_text'],True)
        self.assertEqual(len(model['vpn_connections']),2)
        self.assertTrue(p['yaml_text'].startswith(base))
        self.assertEqual(model['l1'],load_model(base)['l1'])
        svg=render(model)
        self.assertEqual(svg.count('class="vpn-group '),2)
        self.assertIn('10.255.0.1/30',svg);self.assertIn('ポリシー終端',svg)
        self.assertNotIn('class="vpn-group ',render(model,layers=['l1']))
        self.assertNotIn('class="vpn-group ',render(model,layers=['l2']))
        self.assertIn('data-vpn-members=',svg)
        self.assertEqual(element_count(model)-element_count(load_model(base)),2)
        self.assertEqual(display_stats(model,['l3'])['rows']-display_stats(load_model(base),['l3'])['rows'],4)
    def test_unnumbered_route_supported_policy_forbids_tunnel(self):
        doc=copy.deepcopy(self.doc)
        for e in doc['vpn_connections'][0]['endpoints']:e.pop('tunnel_address')
        self.compose(doc)
        doc['vpn_connections'][1]['endpoints'][0]['tunnel_interface']='wrong'
        with self.assertRaisesRegex(ModelError,'ポリシー型'):self.compose(doc)
    def test_invalid_references_ownership_and_duplicate_endpoints(self):
        for field,value in [('device','missing'),('site','wrong'),('subnets',['missing']),('subnets',['osaka::net-office'])]:
            doc=copy.deepcopy(self.doc);doc['vpn_connections'][0]['endpoints'][0][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ModelError):self.compose(doc)
        doc=copy.deepcopy(self.doc);doc['vpn_connections'][0]['endpoints'][1]=copy.deepcopy(doc['vpn_connections'][0]['endpoints'][0])
        with self.assertRaisesRegex(ModelError,'異なる拠点'):self.compose(doc)
    def test_overlap_blocked_before_filtering_and_no_implicit_nat(self):
        base=self.base.replace('192.168.110.','192.168.10.')
        with self.assertRaisesRegex(ModelError,'拠点間で重複'):self.compose(base=base)
        model=yaml.safe_load(base);model['vpn_connections']=self.doc['vpn_connections']
        r=self.client.post('/api/render',json={'yaml_text':yaml.safe_dump(model),'scope':{'site':'hq'}})
        self.assertEqual(r.status_code,422);self.assertIn('重複',r.text)
    def test_route_requires_interface_and_address_pair_and_no_collisions(self):
        for change in ['missing_if','half_address','same_address','lan_address','duplicate_if','overlap_tunnel']:
            doc=copy.deepcopy(self.doc);vpn=doc['vpn_connections'][0]
            if change=='missing_if':vpn['endpoints'][0].pop('tunnel_interface')
            if change=='half_address':vpn['endpoints'][0].pop('tunnel_address')
            if change=='same_address':vpn['endpoints'][1]['tunnel_address']='10.255.0.1/30'
            if change=='lan_address':vpn['endpoints'][0]['tunnel_address']='192.168.10.1/24'
            if change in ['duplicate_if','overlap_tunnel']:
                other=copy.deepcopy(vpn);other['id']='other'
                if change=='overlap_tunnel':
                    for i,e in enumerate(other['endpoints']):e['tunnel_interface']='tunnel1';e['tunnel_address']=f'10.255.0.{i+3}/29'
                doc['vpn_connections'].append(other)
            with self.subTest(change=change),self.assertRaises(ModelError):self.compose(doc)
    def test_duplicate_vpn_id_and_extra_fields_are_rejected(self):
        candidate=self.compose()['yaml_text']
        with self.assertRaisesRegex(ModelError,'重複'):self.compose(base=candidate)
        for key in ['secret','unknown']:
            doc=copy.deepcopy(self.doc);doc['vpn_connections'][0][key]='not-allowed'
            with self.assertRaises(ModelError):self.compose(doc)
    def test_scope_hides_incomplete_vpn_and_focus_expands_target_owners(self):
        model,ix=load_model(self.compose()['yaml_text'],True)
        projected,display,catalog=prepare_view(model,ix,ViewScope(site='hq'))
        self.assertFalse(projected.get('vpn_connections'));self.assertIn('vpn-office',' '.join(display['context_notes']));validate(projected)
        focused,display,_=prepare_view(model,ix,ViewScope(vpn_id='vpn-management'))
        self.assertEqual([v['id'] for v in focused['vpn_connections']],['vpn-management'])
        self.assertEqual({d['id'] for d in focused['devices']},{'hq::gw01','osaka::gw01','hq::sw01','osaka::sw01'})
        validate(focused);self.assertEqual(len(catalog['vpns']),2)
        with self.assertRaises(ModelError):prepare_view(model,ix,ViewScope(vpn_id='missing'))
    def test_api_limits_syntax_busy_and_merged_vpn_remerge_rejection(self):
        for text in ['schema: layermap-vpn/v1\nvpn_connections: &x [*x]','schema: layermap-vpn/v1\nschema: x','not: [']:
            r=self.client.post('/api/vpn/preview',json={'yaml_text':self.base,'connections_yaml':text});self.assertEqual(r.status_code,422)
        r=self.client.post('/api/vpn/preview',json={'yaml_text':self.base,'connections_yaml':self.sample['connections_yaml']});self.assertEqual(r.status_code,200)
        candidate=r.json()['yaml_text'];r=self.client.post('/api/render',json={'yaml_text':candidate});self.assertEqual(r.status_code,200);self.assertIn('vpn-office',r.json()['svg'])
        with self.assertRaisesRegex(ModelError,'再統合'):
            merge_preview(MergeRequest(sources=[dict(site_id=s,filename=s+'.yaml',yaml_text=candidate) for s in ['a','b']]))
        render_slots.acquire();render_slots.acquire()
        try:self.assertEqual(self.client.post('/api/vpn/preview',json={'yaml_text':self.base,'connections_yaml':self.sample['connections_yaml']}).status_code,429)
        finally:render_slots.release();render_slots.release()
    def test_svg_escapes_names_and_keeps_valid_xml(self):
        import xml.etree.ElementTree as ET
        doc=copy.deepcopy(self.doc);doc['vpn_connections'][0]['name']='<script>alert("x")</script>'
        model=load_model(self.compose(doc)['yaml_text']);svg=render(model)
        ET.fromstring(svg);self.assertNotIn('<script>',svg);self.assertIn('&lt;script&gt;',svg)

if __name__=='__main__':unittest.main()
