import copy
from pathlib import Path
import unittest
import yaml
from fastapi.testclient import TestClient
from network_model import load_model,validate,ModelError
from generate_diagram import render
from view_model import prepare_view,ViewScope,TraceRoot,display_stats,element_count
from input_support import DeviceOperation,preview
from web_app import app

SOURCE=Path(__file__).with_name('samples').joinpath('05-management-svi.yaml').read_text(encoding='utf-8')

class SviTests(unittest.TestCase):
    def test_sample_svi_is_independent_and_has_explicit_management_path(self):
        model,ix=load_model(SOURCE,with_index=True)
        self.assertEqual(ix['devices']['sw01']['role'],'l2-switch')
        self.assertEqual(ix['l2.interfaces']['sw01.svi99']['vlan'],'vlan-management')
        self.assertFalse(any(b['l2_interface']=='sw01.svi99' for b in model['bindings']['l2_to_l1']))
        self.assertEqual(len(model['l1']['ports']),6)
        svg=render(model)
        self.assertIn('SVI / 論理VLAN IF・物理ポートなし',svg)
        self.assertIn('SVI / VLAN 99 / sw01.svi99',svg)
        self.assertIn('data-interface-mode="svi"',svg)
        self.assertIn('192.168.99.2/24',svg)

    def test_trace_scope_stops_at_svi_without_projecting_physical_ports(self):
        model,ix=load_model(SOURCE,with_index=True)
        for layer,identity in [('l2','sw01.svi99'),('l3','sw01.management')]:
            projected,display,catalog=prepare_view(model,ix,ViewScope(trace_root=TraceRoot(layer=layer,id=identity)))
            self.assertEqual(display['status'],'ready')
            self.assertEqual(display['counts']['rows'],2)
            self.assertEqual(projected['l1']['ports'],[])
            self.assertEqual(projected['bindings']['l2_to_l1'],[])
            self.assertEqual(projected['l2']['bridges'][0]['members'],['sw01.svi99'])
            validate(projected);render(projected)
        _,_,catalog=prepare_view(model,ix,ViewScope(device_ids=['sw01']))
        self.assertTrue(any(v['id']=='sw01.svi99' for v in catalog['focus_options']))

    def test_invalid_svi_bindings_fields_and_vlan_references_are_rejected(self):
        base=load_model(SOURCE)
        cases=[]
        m=copy.deepcopy(base);m['bindings']['l2_to_l1'].append(dict(l2_interface='sw01.svi99',physical_port='sw01.p1'));cases.append(m)
        m=copy.deepcopy(base);m['l2']['interfaces'][-1]['untagged_vlan']='vlan-management';cases.append(m)
        m=copy.deepcopy(base);m['l2']['interfaces'][-1]['vlan']='missing';cases.append(m)
        m=copy.deepcopy(base);m['bindings']['l3_to_l2'][0]['vlan']='vlan-guest';cases.append(m)
        m=copy.deepcopy(base);m['l2']['interfaces'][0]['vlan']='vlan-office';cases.append(m)
        for case in cases:
            with self.subTest(case=cases.index(case)),self.assertRaises(ModelError):validate(case)

    def test_svi_requires_one_owned_bridge_and_one_svi_per_domain(self):
        base=load_model(SOURCE)
        for members in [[],['sw01.svi99','sw01.svi99']]:
            m=copy.deepcopy(base);m['l2']['bridges'][0]['members']=members
            with self.assertRaises(ModelError):validate(m)
        m=copy.deepcopy(base);m['l2']['interfaces'].append(dict(id='sw01.other-svi',device='sw01',mode='svi',vlan='vlan-management'));m['l2']['bridges'][0]['members'].append('sw01.other-svi')
        with self.assertRaises(ModelError):validate(m)
        m=copy.deepcopy(base);m['l2']['bridges'][0]['device']='gw01'
        with self.assertRaises(ModelError):validate(m)

    def test_svi_can_exist_without_any_physical_port_or_l3_address(self):
        m=load_model(SOURCE);m['devices']=[d for d in m['devices'] if d['id']=='sw01'];m['l1']={'ports':[],'links':[]}
        m['l2']['interfaces']=[i for i in m['l2']['interfaces'] if i['mode']=='svi'];m['l2']['bridges'][0]['members']=['sw01.svi99']
        m['bindings']={'l2_to_l1':[],'l3_to_l2':[]};m['l3']['interfaces']=[];m['l3']['routes']=[]
        validate(m);render(m)
        self.assertEqual(display_stats(m)['rows'],1)

    def test_dual_stack_addresses_share_one_svi(self):
        m=load_model(SOURCE);m['l3']['subnets'].append(dict(id='net6',cidr='2001:db8:99::/64'))
        m['l3']['interfaces'].append(dict(id='sw01.management6',device='sw01',address='2001:db8:99::2/64',subnet='net6'))
        m['bindings']['l3_to_l2'].append(dict(l3_interface='sw01.management6',l2_interface='sw01.svi99',vlan='vlan-management'))
        ix=validate(m);projected,display,_=prepare_view(m,ix,ViewScope(trace_root=TraceRoot(layer='l2',id='sw01.svi99')))
        self.assertEqual(display['counts']['rows'],3);render(projected)

    def test_wizard_svi_keeps_physical_vlan_and_existing_comments_untouched(self):
        operation=DeviceOperation(type='device',device={'id':'new-switch','role':'l2-switch'},port_count=2,vlans=['vlan-office'],address='192.168.99.3/24',subnet='net-management',ip_vlan='vlan-management',ip_attachment='svi',gateway='192.168.99.1')
        source='# 😀 comment\r\n'+SOURCE.replace('\n','\r\n')
        result=preview(source,operation);m,ix=load_model(result['yaml_text'],with_index=True)
        self.assertEqual(ix['l2.interfaces']['new-switch.p1.l2']['untagged_vlan'],'vlan-office')
        self.assertEqual(ix['l2.interfaces']['new-switch.svi']['vlan'],'vlan-management')
        self.assertFalse(any(b['l2_interface']=='new-switch.svi' for b in m['bindings']['l2_to_l1']))
        raw=source.encode('utf-16-le')
        for edit in reversed(result['changes']):raw=raw[:edit['from']*2]+edit['insert'].encode('utf-16-le')+raw[edit['to']*2:]
        self.assertEqual(raw.decode('utf-16-le'),result['yaml_text']);self.assertNotIn('\n',result['yaml_text'].replace('\r\n',''))
        self.assertGreater(element_count(m),element_count(load_model(SOURCE)))
        for overrides in [{'device':{'id':'bad','role':'endpoint'}},{'configure_l2':False},{'address':None}]:
            values=operation.model_dump();values.update(overrides)
            with self.assertRaises(ModelError):preview(SOURCE,DeviceOperation(**values))

    def test_api_svi_sample_validation_and_filtered_rendering(self):
        client=TestClient(app);self.assertEqual(client.get('/api/samples/management-svi').status_code,200)
        for view in ['all','l1','l2','l3']:
            r=client.post('/api/render',json=dict(yaml_text=SOURCE,view=view))
            self.assertEqual(r.status_code,200,r.text)
        m=load_model(SOURCE);m['bindings']['l2_to_l1'].append(dict(l2_interface='sw01.svi99',physical_port='sw01.p1'))
        r=client.post('/api/render',json=dict(yaml_text=yaml.safe_dump(m),scope={'device_ids':['pc-a']}))
        self.assertEqual(r.status_code,422)

if __name__=='__main__':unittest.main()
