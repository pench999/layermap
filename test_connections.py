import copy
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
import yaml
from fastapi.testclient import TestClient
from network_model import load_model, validate, ModelError
from generate_diagram import render
from view_model import prepare_view, ViewScope, TraceRoot, display_stats, element_count
from web_app import app


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.source=Path('samples/04-wired-wifi-status.yaml').read_text(encoding='utf-8')
        self.model,self.ix=load_model(self.source,with_index=True)

    def test_sample_current_observations_and_svg_have_no_invented_ports(self):
        response=TestClient(app).post('/api/render',json={'yaml_text':self.source})
        self.assertEqual(response.status_code,200,response.text)
        data=response.json();self.assertEqual(data['counts'],{'devices':10,'links':9,'vlans':2})
        root=ET.fromstring(data['svg'])
        cls=lambda name:[e for e in root.iter() if name in e.attrib.get('class','').split()]
        self.assertEqual(len(cls('wifi-wave')),4)
        self.assertEqual(len(cls('wired-path')),2)
        self.assertEqual(len(cls('physical-cable')),3)
        self.assertEqual(len(cls('unresolved-endpoint')),2)
        self.assertEqual(len(cls('unknown-peer')),2)
        actual=[e.attrib['data-element-id'] for e in root.iter() if e.attrib.get('data-owner')=='sw01']
        self.assertFalse(any('unknown' in value for value in actual))
        self.assertTrue(all('Q' in e.attrib['d'] for e in cls('wifi-wave')))
        self.assertTrue(all(e.attrib.get('stroke-dasharray')=='10 3 2 3' for e in cls('wired-path')))
        self.assertIn('2026-10-16T10:00:00+09:00',data['svg'])
        # Every new connection is represented by exactly one visible path.
        for group in cls('l1-connection'):
            self.assertEqual(len([e for e in group if e.tag.endswith('path')]),1)
        self.assertEqual(len([p for p in self.model['l1']['ports'] if p['id']=='ap01.wlan0']),1)

    def test_invalid_status_endpoint_kind_and_evidence_combinations_are_rejected(self):
        cases=[]
        def mutate(fn):
            model=copy.deepcopy(self.model);fn(model);cases.append(model)
        mutate(lambda m:m['l1']['connections'][0].update(status='confirmed'))
        mutate(lambda m:m['l1']['connections'][0]['endpoints'][1].update(port='sw01.p2'))
        mutate(lambda m:m['l1']['connections'][0].update(ssid='not-wifi'))
        mutate(lambda m:m['l1']['connections'][2].update(kind='wired'))
        mutate(lambda m:m['l1']['connections'][2].update(observed_at='2026-10-16'))
        mutate(lambda m:m['l1']['connections'][2].update(observed_at='yesterday'))
        mutate(lambda m:m['l1']['connections'][2].update(endpoints=[{'unknown':True},{'unknown':True}],status='peer_unknown'))
        mutate(lambda m:m['l1']['connections'][2]['endpoints'][1].update(port='missing-radio'))
        mutate(lambda m:m['l1']['connections'][2].update(endpoints=[{'port':'ap01.wlan0'},{'port':'ap01.wlan0'}]))
        mutate(lambda m:m['l1']['connections'][0].update(id='cable-b'))
        mutate(lambda m:m['l1']['connections'][0]['endpoints'][0].update(port='pc-b.eth0'))
        for model in cases:
            with self.subTest(model=model['l1']['connections']):
                with self.assertRaises(ModelError):load_model(yaml.safe_dump(model,allow_unicode=True))
        response=TestClient(app).post('/api/render',json={'yaml_text':yaml.safe_dump(cases[0]),'scope':{'device_ids':['gw01']}})
        self.assertEqual(response.status_code,422)
        self.assertEqual(response.json()['errors'][0]['path'],'l1.connections[0].status')
        self.assertIsNotNone(response.json()['errors'][0]['line'])

    def test_confirmed_wired_uses_actual_ports_and_blocks_duplicate_occupancy(self):
        model=copy.deepcopy(self.model)
        old=model['l1']['links'].pop(0)
        model['l1']['connections'].append({'id':old['id'],'kind':'wired','status':'confirmed','endpoints':[{'port':p} for p in old['endpoints']]})
        validate(model);svg=render(model)
        root=ET.fromstring(svg)
        group=next(e for e in root.iter() if e.attrib.get('data-connection-id')=='cable-b')
        path=next(e for e in group if e.tag.endswith('path'))
        self.assertNotIn('stroke-dasharray',path.attrib)
        self.assertNotIn('Q',path.attrib['d'])
        model['l1']['links'].append(old)
        with self.assertRaises(ModelError):validate(model)

    def test_unknown_labels_escape_text_and_expand_for_long_ssids(self):
        model=copy.deepcopy(self.model)
        model['l1']['connections'][-1]['ssid']='<script>alert(1)</script>" onload="x'+'あ'*100
        model['l1']['connections'][0]['id']='long-'+'x'*90
        svg=render(model)
        root=ET.fromstring(svg)
        self.assertNotIn('<script>',svg)
        self.assertFalse(any('onload' in e.attrib for e in root.iter()))
        unknown=next(e for e in root.iter() if e.attrib.get('class')=='unknown-peer' and e.attrib.get('data-connection-id')=='wifi-ap-unknown')
        rect=next(e for e in unknown if e.tag.endswith('rect'))
        self.assertTrue(all(float(e.attrib['y'])<float(rect.attrib['y'])+float(rect.attrib['height']) for e in unknown if e.tag.endswith('text')))

    def test_filters_preserve_unknown_peers_and_report_known_hidden_devices(self):
        original=copy.deepcopy(self.model)
        projected,display,_=prepare_view(self.model,self.ix,ViewScope(device_ids=['wifi4']))
        self.assertEqual([c['id'] for c in projected['l1']['connections']],['wifi-ap-unknown'])
        self.assertEqual(display['boundary_links']['total'],0)
        self.assertEqual([d['id'] for d in projected['devices']],['wifi4'])
        self.assertIn('AP未確認',render(projected))
        projected,display,_=prepare_view(self.model,self.ix,ViewScope(device_ids=['ap01']))
        self.assertEqual(display['boundary_links']['total'],4)
        self.assertEqual(display['boundary_links']['noun'],'L1接続')
        self.assertNotIn('wifi-ap-unknown',[c['id'] for c in display['boundary_links']['items']])
        validate(projected);render(projected)
        self.assertEqual(self.model,original)
        trace=ViewScope(trace_root=TraceRoot(layer='l3',id='wifi1.office.ip'))
        projected,display,_=prepare_view(self.model,self.ix,trace)
        self.assertEqual([d['id'] for d in projected['devices']],['wifi1'])
        self.assertEqual(display['boundary_links']['total'],1)

    def test_budget_counts_connections_and_visual_unknown_endpoints(self):
        without=copy.deepcopy(self.model);without['l1']['connections']=[]
        self.assertEqual(element_count(self.model)-element_count(without),6)
        stats=display_stats(self.model,layers=['l1'])
        self.assertEqual(stats['connections'],9)
        self.assertEqual(stats['rows'],17)
        self.assertEqual(stats['elements'],32)


if __name__=='__main__':unittest.main()