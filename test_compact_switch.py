import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
import yaml
from generate_diagram import render

class CompactSwitchTests(unittest.TestCase):
    def test_dense_switch_compacts_without_losing_ports_or_memberships(self):
        model=yaml.safe_load(Path('samples/12-three-48port-switches.yaml').read_text())
        full=ET.fromstring(render(model))
        compact=ET.fromstring(render(model,layers=['l2']))
        for device in ['sw01','sw02','sw03']:
            before=next(e for e in full.iter() if e.get('data-device')==device and e.get('data-device-layer')=='l2')
            after=next(e for e in compact.iter() if e.get('data-device')==device)
            frame=lambda card:next(e for e in card if e.get('class')=='device-frame')
            self.assertLess(float(frame(after).get('height')),float(frame(before).get('height'))/3)
            groups=[e for e in after if 'switch-vlan-group' in e.get('class','').split()]
            self.assertTrue(groups)
            self.assertEqual(len(groups),len({e.get('data-network-id') for e in groups}))
            chips=[e for e in after.iter() if 'compact-port' in e.get('class','').split()]
            self.assertEqual(len(chips),sum(i['device']==device and i['mode']=='access' for i in model['l2']['interfaces']))
            self.assertEqual({e.get('data-element-id') for e in chips},{i['id'] for i in model['l2']['interfaces'] if i['device']==device and i['mode']=='access'})
        for net in [e for e in compact.iter() if 'network-group' in e.get('class','').split()]:
            if net.get('data-network-kind')!='vlan':continue
            import json
            actual={i for b in net if b.get('class')=='relation-branch' for i in json.loads(b.get('data-endpoints'))}
            from network_model import interface_vlans
            expected={i['id'] for i in model['l2']['interfaces'] if net.get('data-network-id') in interface_vlans(i)}
            self.assertEqual(actual,expected)
        # Compact view must not mutate the persisted model or full tracing view.
        self.assertFalse(any('compact-port' in e.get('class','').split() for e in ET.fromstring(render(model)).iter()))

    def test_fifty_access_ports_form_four_vlan_frames(self):
        device='sw';ports=[{'id':f'sw.p{n}','device':device,'name':f'port{n}'} for n in range(1,51)]
        interfaces=[{'id':p['id']+'.l2','device':device,'mode':'access','untagged_vlan':'v'+str(1 if n==1 else 10 if n<=8 else 100 if n<=30 or n>=49 else 200)} for n,p in enumerate(ports,1)]
        model={'schema':'lan-example/v1','name':'50 ports','devices':[{'id':device,'role':'l2-switch'}],'l1':{'ports':ports,'links':[]},'l2':{'vlans':[{'id':'v'+str(n),'tag':n} for n in [1,10,100,200]],'interfaces':interfaces,'bridges':[{'id':'sw.bridge','device':device,'members':[i['id'] for i in interfaces]}]},'l3':{'subnets':[],'interfaces':[],'routes':[]},'bindings':{'l2_to_l1':[{'l2_interface':i['id'],'physical_port':p['id']} for i,p in zip(interfaces,ports)],'l3_to_l2':[]}}
        root=ET.fromstring(render(model,layers=['l2']))
        groups=[e for e in root.iter() if 'switch-vlan-group' in e.get('class','').split()]
        self.assertEqual(len(groups),4)
        self.assertEqual([len([e for e in g.iter() if 'compact-port' in e.get('class','').split()]) for g in groups],[1,7,24,18])
        self.assertLess(float(next(e for e in root.iter() if e.get('class')=='device-frame').get('height')),1400)
