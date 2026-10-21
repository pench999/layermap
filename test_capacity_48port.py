import copy
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from fastapi.testclient import TestClient
from pydantic import ValidationError
from bench_48port import make_48port_model,long_reference_model
from bench_scale import make_model,encode
from network_model import load_model,MAX_DEVICE_PORTS
from input_support import DeviceOperation,preview
from view_model import prepare_view,ViewScope,display_stats,budget_errors,limits,MAX_SVG_BYTES,element_count
from generate_diagram import render
from web_app import app

class CapacityTests(unittest.TestCase):
    def test_three_48port_switches_and_hosts_render_without_omitting_ports(self):
        m=make_48port_model();model,ix=load_model(encode(m),True)
        projected,display,_=prepare_view(model,ix)
        self.assertEqual(display['status'],'ready')
        self.assertEqual(display['counts'],dict(devices=15,rows=414,connections=662,elements=720,groups=10))
        root=ET.fromstring(render(projected))
        rows=[e for e in root.iter() if 'interface-row' in e.get('class','').split()]
        self.assertEqual(len(rows),414)
        for d in ['sw01','sw02','sw03']:
            self.assertEqual(sum(e.get('data-owner')==d and e.get('data-interface-mode')=='physical' for e in rows),48)
        self.assertEqual(sum(e.get('class')=='physical-cable' for e in root.iter()),50)

    def test_row_boundary_and_layer_specific_budget(self):
        m=make_model(20,10);model,ix=load_model(encode(m),True)
        self.assertEqual(prepare_view(model,ix)[1]['counts']['rows'],600)
        self.assertEqual(prepare_view(model,ix)[1]['status'],'ready')
        m['l1']['ports'].append(dict(id='extra',device='d000'));model,ix=load_model(encode(m),True)
        self.assertEqual(prepare_view(model,ix)[1]['status'],'too_large')
        self.assertEqual(prepare_view(model,ix,layers=['l1'])[1]['status'],'ready')
        at=dict(devices=24,rows=600,connections=1200,elements=1600,groups=80)
        self.assertEqual(budget_errors(at),[])
        for field in at:
            over=dict(at);over[field]+=1
            self.assertEqual(len(budget_errors(over)),1)

    def test_21_hosts_fit_and_dense_membership_overflow_is_explicit(self):
        model,ix=load_model(encode(make_48port_model(21)),True)
        self.assertEqual(prepare_view(model,ix)[1]['status'],'ready')
        self.assertEqual(prepare_view(model,ix)[1]['counts']['devices'],24)
        model,ix=load_model(encode(make_model(1,18,dense=True)),True)
        self.assertEqual(prepare_view(model,ix)[1]['status'],'too_large')
        self.assertEqual(prepare_view(model,ix)[1]['counts']['connections'],1224)
        self.assertEqual(prepare_view(model,ix,ViewScope(device_ids=['d000'],trace_root={'layer':'l1','id':'d000.p00'}))[1]['status'],'ready')

    def test_large_svg_accepts_long_identifiers_and_enforces_byte_boundary(self):
        m=long_reference_model();load_model(encode(m));drawing=render(m)
        self.assertGreater(len(drawing.encode('utf-8')),4*1024*1024)
        self.assertLess(len(drawing.encode('utf-8')),MAX_SVG_BYTES)
        client=TestClient(app);source=encode(make_model())
        exact='<svg>'+(' '*(MAX_SVG_BYTES-len('<svg></svg>')))+'</svg>'
        with patch('web_app.render',return_value=exact):
            r=client.post('/api/render',json={'yaml_text':source});self.assertEqual(r.status_code,200)
            self.assertEqual(len(r.json()['svg'].encode('utf-8')),MAX_SVG_BYTES)
        with patch('web_app.render',return_value=exact+' '):
            r=client.post('/api/render',json={'yaml_text':source});self.assertEqual(r.status_code,200)
            self.assertEqual(r.json()['display']['status'],'too_large');self.assertEqual(r.json()['svg'],'')

    def test_wizard_supports_48_data_ports_and_4_uplinks(self):
        source=encode(make_model(1,1))
        for ports in [48,52,64]:
            operation=DeviceOperation(type='device',device={'id':'added','role':'l2-switch'},port_count=ports,vlans=['v10'])
            result=preview(source,operation);model,ix=load_model(result['yaml_text'],True)
            self.assertEqual(sum(p['device']=='added' for p in model['l1']['ports']),ports)
            self.assertEqual(sum(p['device']=='added' for p in model['l2']['interfaces']),ports)
            self.assertEqual(prepare_view(model,ix)[1]['status'],'ready')
        self.assertEqual(limits()['wizard_ports'],MAX_DEVICE_PORTS)
        with self.assertRaises(ValidationError):DeviceOperation(type='device',device={'id':'added','role':'l2-switch'},port_count=65)

    def test_filtering_retains_inventory_and_invalid_hidden_reference_is_rejected(self):
        m=make_48port_model();source=encode(m);client=TestClient(app)
        response=client.post('/api/render',json={'yaml_text':source,'scope':{'device_ids':['sw01']}})
        self.assertEqual(response.status_code,200)
        result=response.json();self.assertEqual(result['counts']['devices'],15);self.assertEqual(result['display']['counts']['rows'],98)
        self.assertEqual(result['display']['boundary_links']['total'],13)
        m['bindings']['l2_to_l1'][-1]['physical_port']='missing-hidden-port'
        response=client.post('/api/render',json={'yaml_text':encode(m),'scope':{'device_ids':['sw01']}})
        self.assertEqual(response.status_code,422)
