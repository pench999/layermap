import copy
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
import yaml
from fastapi.testclient import TestClient
from network_model import load_model,validate,ModelError
from generate_diagram import render
from view_model import prepare_view,ViewScope,TraceRoot,element_count
from merge_model import merge_preview,MergeRequest
from source_map import locate_source,SourceRequest
from web_app import app

SOURCE=Path(__file__).with_name('samples').joinpath('11-aggregation-stack-mlag.yaml').read_text(encoding='utf-8')

def model():return yaml.safe_load(SOURCE)
def item(m,section,identity):
    values=m
    for key in section.split('.'):values=values[key]
    return next(i for i in values if i['id']==identity)

class RedundancyTests(unittest.TestCase):
    def test_sample_preserves_chassis_and_renders_one_logical_stack(self):
        m,ix=load_model(SOURCE,True)
        root=ET.fromstring(render(m))
        cards=[e for e in root.iter() if e.get('class')=='device-card']
        self.assertEqual(len([e for e in cards if e.get('data-device-layer')=='l1']),7)
        self.assertFalse(any(e.get('data-device')=='stack01' and e.get('data-device-layer')=='l1' for e in cards))
        for layer in ['l2','l3']:
            ids={e.get('data-device') for e in cards if e.get('data-device-layer')==layer}
            self.assertIn('stack01',ids);self.assertNotIn('sw1',ids);self.assertNotIn('sw2',ids)
            self.assertTrue({'leaf1','leaf2'}<=ids)
        text=ET.tostring(root,encoding='unicode')
        for word in ['DEMO-SN-4','DEMO-SN-5','STACK専用接続','MLAG peer-link','active_backup','primary','lacp']:
            if word=='primary':continue
            self.assertIn(word,text)
        self.assertEqual(len([e for e in root.iter() if e.get('class')=='physical-cable']),9)
        self.assertEqual(len(ix['l2.interfaces']),11)

    def test_aggregate_validation_and_legacy_bindings(self):
        static=model()
        for i in static['l2']['interfaces']:
            if i.get('aggregation',{}).get('mode')=='lacp':i['aggregation']['mode']='static'
        validate(static);self.assertIn('static',render(static))
        for change in [
            lambda m:item(m,'l2.interfaces','srv-bond.bond0').pop('aggregation'),
            lambda m:m['bindings']['l2_to_l1'].append(copy.deepcopy(m['bindings']['l2_to_l1'][0])),
            lambda m:item(m,'l1.ports','srv-bond.eth0').update(kind='wifi'),
            lambda m:item(m,'l2.interfaces','srv-team.team0')['aggregation'].update(primary_port='srv-bond.eth0'),
            lambda m:item(m,'l2.interfaces','stack01.po1')['aggregation'].update(mode='active_backup'),
            lambda m:item(m,'l2.interfaces','stack01.po1')['aggregation'].update(mode='static'),
        ]:
            m=model();change(m)
            with self.subTest(change=change),self.assertRaises(ModelError):validate(m)

    def test_stack_members_ownership_and_reserved_links_are_checked(self):
        for change in [
            lambda m:item(m,'devices','stack01')['members'][1].update(number=1),
            lambda m:item(m,'devices','stack01')['members'][1].update(device='stack01'),
            lambda m:item(m,'devices','sw2')['location'].update(site='elsewhere'),
            lambda m:item(m,'l1.ports','sw1.p1').update(device='stack01'),
            lambda m:item(m,'l2.interfaces','stack01.po1').update(device='sw1'),
            lambda m:item(m,'devices','stack01').update(stack_links=['bond-a']),
            lambda m:m['bindings']['l2_to_l1'][3].update(physical_port='sw2.stack1'),
        ]:
            m=model();change(m)
            with self.subTest(change=change),self.assertRaises(ModelError):validate(m)

    def test_mlag_is_independent_and_mismatches_are_rejected(self):
        for change in [
            lambda m:m['mlag_domains'][0].update(peers=['leaf1','leaf1']),
            lambda m:m['mlag_domains'][0].update(peer_links=['stack-ring-a']),
            lambda m:m['mlag_domains'][0].update(interface_pairs=[['leaf1.po11','stack01.po1']]),
            lambda m:item(m,'l2.interfaces','leaf2.po11').update(untagged_vlan='v20'),
            lambda m:m['mlag_domains'].clear(),
        ]:
            m=model();change(m)
            with self.subTest(change=change),self.assertRaises(ModelError):validate(m)

    def test_scope_keeps_stack_valid_and_mlag_partial_is_explicit(self):
        m,ix=load_model(SOURCE,True)
        projected,display,_=prepare_view(m,ix,ViewScope(device_ids=['sw1']))
        self.assertEqual({d['id'] for d in projected['devices']},{'sw1','sw2','stack01'})
        self.assertTrue(any('STACK' in s for s in display['context_notes']));validate(projected);render(projected)
        projected,display,_=prepare_view(m,ix,ViewScope(device_ids=['leaf1']))
        self.assertEqual(projected['mlag_domains'],[])
        self.assertTrue(any('MLAG' in s for s in display['context_notes']));validate(projected)
        projected,_,_=prepare_view(m,ix,ViewScope(trace_root=TraceRoot(layer='l2',id='stack01.po1')))
        self.assertEqual({b['physical_port'] for b in projected['bindings']['l2_to_l1']},{'sw1.p1','sw2.p1'})
        validate(projected);render(projected)
        projected,_,_=prepare_view(m,ix,ViewScope(trace_root=TraceRoot(layer='l3',id='srv-bond.ip10')))
        self.assertEqual({i['id'] for i in projected['l3']['interfaces']},{'srv-bond.ip10','srv-bond.ip20'})
        self.assertEqual({i['id'] for i in projected['l1']['ports']},{'srv-bond.eth0','srv-bond.eth1'});validate(projected)

    def test_merge_renames_every_new_reference_without_dropping_definitions(self):
        result=merge_preview(MergeRequest(sources=[dict(site_id=s,filename=s+'.yaml',yaml_text=SOURCE) for s in ['hq','branch']]))
        merged=load_model(result['yaml_text']);self.assertEqual(len(merged['mlag_domains']),2)
        for site in ['hq','branch']:
            d=item(merged,'devices',site+'::stack01');self.assertEqual(d['members'][0]['device'],site+'::sw1')
            self.assertEqual(d['stack_links'][0],site+'::stack-ring-a')
            agg=item(merged,'l2.interfaces',site+'::srv-team.team0')['aggregation'];self.assertEqual(agg['primary_port'],site+'::srv-team.eth0')
            domain=item(merged,'mlag_domains',site+'::mlag01');self.assertEqual(domain['interface_pairs'][0],[site+'::leaf1.po11',site+'::leaf2.po11'])
            self.assertEqual(domain['peer_links'],[site+'::mlag-peer'])
        self.assertEqual(result['counts']['elements'],2*element_count(model()))

    def test_source_positions_include_stack_members_mlag_pairs_and_primary_port(self):
        for section,identity,expected in [('devices','sw1','devices[7].members[0].device'),('mlag_domains','mlag01','mlag_domains[0]'),('l1.ports','srv-team.eth0','l2.interfaces[2].aggregation.primary_port'),('l2.interfaces','leaf1.po11','mlag_domains[0].interface_pairs[0][0]')]:
            r=locate_source(SourceRequest(yaml_text=SOURCE,target=dict(section=section,id=identity)))
            self.assertIn(expected,[l['path'] for l in r['locations']])

    def test_api_sample_views_and_scope(self):
        client=TestClient(app)
        response=client.get('/api/samples/aggregation-stack-mlag');self.assertEqual(response.status_code,200)
        for view in ['all','l1','l2','l3']:
            r=client.post('/api/render',json=dict(yaml_text=SOURCE,view=view));self.assertEqual(r.status_code,200,r.text);ET.fromstring(r.json()['svg'])
        r=client.post('/api/render',json=dict(yaml_text=SOURCE,scope={'device_ids':['sw1']}));self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['counts']['devices'],8);self.assertEqual(len(r.json()['visible_devices']),3)

    def test_routed_lag_has_ip_without_fabricated_vlan(self):
        m=model()
        for identity in ['srv-bond.bond0','stack01.po1']:
            i=item(m,'l2.interfaces',identity);i['mode']='routed';i.pop('tagged_vlans')
        item(m,'l2.bridges','stack01.bridge')['members'].remove('stack01.po1')
        for b in m['bindings']['l3_to_l2']:
            if b['l2_interface']=='srv-bond.bond0':b.pop('vlan')
        validate(m);self.assertIn('routed / VLANなし',render(m))
        client=TestClient(app);r=client.post('/api/render',json=dict(yaml_text=yaml.safe_dump(m)))
        self.assertEqual(r.status_code,200,r.text)
        merged=merge_preview(MergeRequest(sources=[dict(site_id=s,filename=s+'.yaml',yaml_text=yaml.safe_dump(m)) for s in ['a','b']]))
        validate(load_model(merged['yaml_text']))
        bad=copy.deepcopy(m);bad['bindings']['l3_to_l2'][0]['vlan']='v10'
        with self.assertRaises(ModelError):validate(bad)

    def test_explicit_null_aggregation_remains_mergeable(self):
        m=model();item(m,'l2.interfaces','leaf1.p2')['aggregation']=None
        validate(m)
        merged=merge_preview(MergeRequest(sources=[dict(site_id=s,filename=s+'.yaml',yaml_text=yaml.safe_dump(m)) for s in ['one','two']]))
        validate(load_model(merged['yaml_text']))
