"""Behavior checks: changed data, topology growth, invalid references, escaping."""
import copy
import unittest
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml
from generate_diagram import render, ModelError


class DiagramTests(unittest.TestCase):
    def setUp(self):
        self.model = yaml.safe_load(Path(__file__).with_name('lan-sample.yaml').read_text(encoding='utf-8'))

    def test_sample_and_changed_inventory(self):
        self.model['devices'][0]['name'] = 'PC <new> & test'
        self.model['devices'][0]['serial_number'] = 'NEW-SERIAL'
        output = render(self.model)
        root = ET.fromstring(output)
        text = ''.join(root.itertext())
        self.assertIn('PC <new> & test', text)
        self.assertIn('NEW-SERIAL', text)
        for layer in ['L1 /', 'L2 /', 'L3 /']:
            self.assertIn(layer, text)

    def test_new_device_vlan_subnet_and_bindings(self):
        m = self.model
        m['devices'].append({'id':'newpc', 'name':'New PC'})
        m['l1']['ports'].append({'id':'newpc.eth0', 'device':'newpc'})
        m['l1']['ports'].append({'id':'sw01.p3', 'device':'sw01'})
        m['l1']['links'].append({'id':'new-cable', 'endpoints':['newpc.eth0','sw01.p3']})
        m['l2']['vlans'].append({'id':'new-vlan','tag':30})
        for key, dev in [('newpc.l2','newpc'), ('sw01.a3','sw01')]:
            m['l2']['interfaces'].append({'id':key,'device':dev,'mode':'access','untagged_vlan':'new-vlan'})
        m['l2']['bridges'][0]['members'].append('sw01.a3')
        m['l3']['subnets'].append({'id':'new-net','cidr':'192.168.30.0/24'})
        m['l3']['interfaces'].append({'id':'newpc.ip','device':'newpc','address':'192.168.30.2/24','subnet':'new-net'})
        m['bindings']['l2_to_l1'] += [
            {'l2_interface':'newpc.l2','physical_port':'newpc.eth0'},
            {'l2_interface':'sw01.a3','physical_port':'sw01.p3'}]
        m['bindings']['l3_to_l2'].append({'l3_interface':'newpc.ip','l2_interface':'newpc.l2','vlan':'new-vlan'})
        output = render(m)
        ET.fromstring(output)
        for value in ['newpc.eth0','newpc.l2','newpc.ip','new-vlan','new-cable','192.168.30.2/24']:
            self.assertIn(value, output)

    def test_unknown_reference_rejected(self):
        self.model['l1']['links'][0]['endpoints'][0] = 'missing.port'
        with self.assertRaises(ModelError):
            render(self.model)

    def test_vlan_and_subnet_mismatch_rejected(self):
        changed = copy.deepcopy(self.model)
        changed['bindings']['l3_to_l2'][0]['vlan'] = 'vlan-guest'
        with self.assertRaises(ModelError):
            render(changed)
        self.model['l3']['interfaces'][0]['address'] = '10.0.0.1/24'
        with self.assertRaises(ModelError):
            render(self.model)

    def test_watch_updates_and_preserves_valid_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'test.yaml'
            target = source.with_suffix('.svg')
            source.write_text(yaml.safe_dump(self.model, allow_unicode=True), encoding='utf-8')
            script = Path(__file__).with_name('generate_diagram.py')
            process = subprocess.Popen([sys.executable, str(script), str(source), '--watch'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            def wait_for(predicate):
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    if predicate():
                        return
                    time.sleep(0.1)
                self.fail('watch update timed out')
            try:
                wait_for(target.exists)
                self.model['devices'][0]['serial_number'] = 'WATCH-UPDATED'
                source.write_text(yaml.safe_dump(self.model, allow_unicode=True), encoding='utf-8')
                wait_for(lambda: 'WATCH-UPDATED' in target.read_text(encoding='utf-8'))
                previous = target.read_bytes()
                source.write_text('schema: broken', encoding='utf-8')
                time.sleep(1.5)
                self.assertIsNone(process.poll())
                self.assertEqual(previous, target.read_bytes())
            finally:
                process.terminate()
                process.wait(timeout=5)

    def test_one_frame_per_device_per_layer_and_interfaces_remain_distinct(self):
        root = ET.fromstring(render(self.model))
        for layer, key in [('l1','ports'),('l2','interfaces'),('l3','interfaces')]:
            panel = next(e for e in root.iter() if e.attrib.get('data-layer') == layer)
            cards = [e for e in panel.iter() if e.attrib.get('class') == 'device-card']
            self.assertEqual(len(cards), len(self.model['devices']))
            for device in self.model['devices']:
                matches = [e for e in cards if e.attrib['data-device'] == device['id']]
                self.assertEqual(len(matches),1)
                card = matches[0]
                self.assertEqual(len([e for e in card.iter() if e.tag.endswith('rect')]),1)
                expected = {i['id'] for i in self.model[layer][key] if i['device']==device['id']}
                self.assertEqual({e.attrib['data-element-id'] for e in card.iter() if 'data-element-id' in e.attrib}, expected)
        l1 = next(e for e in root.iter() if e.attrib.get('data-device-layer')=='l1' and e.attrib.get('data-device')=='sw01')
        self.assertIn('DEMO-SW-0001',''.join(l1.itertext()))
        self.assertNotIn('L1 機器台帳',''.join(root.itertext()))

    def test_cables_and_cross_layer_bindings_use_individual_row_anchors(self):
        root = ET.fromstring(render(self.model))
        nodes = {}
        for layer in [e for e in root.iter() if 'data-layer' in e.attrib]:
            for row in layer.iter():
                if 'data-element-id' in row.attrib:
                    nodes[(layer.attrib['data-layer'],row.attrib['data-element-id'])] = float(row.attrib['data-anchor-y'])
            for branch in layer.iter():
                if 'data-endpoint' in branch.attrib:
                    first = branch.attrib['d'].split(' L')[0][1:]
                    anchor=next(e for e in layer.iter() if e.attrib.get('data-membership-interface')==branch.attrib['data-endpoint'] and e.attrib.get('data-membership-network')==branch.attrib['data-network'])
                    self.assertEqual(tuple(map(float,first.split(','))),(float(anchor.attrib['cx']),float(anchor.attrib['cy'])))
        switch_ports = [nodes[('l1',p)] for p in ['sw01.p1','sw01.p2','sw01.p24']]
        self.assertEqual(len(set(switch_ports)),3)
        for binding in [e for e in root.iter() if 'data-binding' in e.attrib]:
            upper, lower = ('l3','l2') if binding.attrib['data-binding']=='l3_to_l2' else ('l2','l1')
            for edge in [e for e in binding.iter() if 'data-from' in e.attrib]:
                points = edge.attrib['d'][1:].split(' L')
                self.assertEqual(float(points[0].split(',')[1]),nodes[(upper,edge.attrib['data-from'])])
                self.assertEqual(float(points[-1].split(',')[1]),nodes[(lower,edge.attrib['data-to'])])

    def test_frame_grows_for_many_ports_and_wrapped_metadata(self):
        baseline = ET.fromstring(render(self.model,layers=['l1']))
        previous_height = float(baseline.attrib['height'])
        for n in range(12):
            self.model['l1']['ports'].append({'id':'sw01.extra'+str(n),'device':'sw01','name':'長いインターフェース名'*8})
        self.model['devices'][2]['serial_number'] = 'LONG-SERIAL-'*12
        root = ET.fromstring(render(self.model,layers=['l1']))
        self.assertGreater(float(root.attrib['height']),previous_height)
        card = next(e for e in root.iter() if e.attrib.get('data-device')=='sw01')
        frame = next(e for e in card if e.attrib.get('class')=='device-frame')
        bottom = float(frame.attrib['y'])+float(frame.attrib['height'])
        rows = [e for e in card.iter() if 'data-anchor-y' in e.attrib]
        self.assertEqual(len(rows),15)
        for row in rows:
            self.assertLess(float(row.attrib['data-anchor-y']),bottom)
            for label in [e for e in row.iter() if e.tag.endswith('text')]:
                self.assertLess(float(label.attrib['y']),bottom)

    def test_each_l1_cable_is_one_path_between_real_port_anchors(self):
        root=ET.fromstring(render(self.model,layers=['l1']))
        anchors={e.attrib['data-port-id']:(float(e.attrib['cx']),float(e.attrib['cy'])) for e in root.iter() if 'data-port-id' in e.attrib}
        groups=[e for e in root.iter() if 'data-cable-id' in e.attrib]
        self.assertEqual(len(groups),len(self.model['l1']['links']))
        self.assertFalse(any(e.attrib.get('class') in ('relation-bus','relation-branch') for e in root.iter()))
        links={l['id']:l for l in self.model['l1']['links']}
        for group in groups:
            paths=[e for e in group.iter() if e.tag.endswith('path')]
            self.assertEqual(len(paths),1)
            wire=paths[0]
            link=links[group.attrib['data-cable-id']]
            self.assertEqual([wire.attrib['data-from'],wire.attrib['data-to']],link['endpoints'])
            points=[tuple(map(float,p.split(','))) for p in wire.attrib['d'][1:].split(' L')]
            self.assertEqual(points[0],anchors[link['endpoints'][0]])
            self.assertEqual(points[-1],anchors[link['endpoints'][1]])
            self.assertIn(link['endpoints'][0],group.attrib['aria-label'])
            self.assertIn(link['endpoints'][1],group.attrib['aria-label'])

    def test_sample_cables_do_not_cross_share_segments_or_pass_through_cards(self):
        root=ET.fromstring(render(self.model,layers=['l1']))
        boxes=[tuple(float(e.attrib[k]) for k in ('x','y','width','height')) for e in root.iter() if e.attrib.get('class')=='device-frame']
        wires=[]
        for wire in [e for e in root.iter() if e.attrib.get('class')=='physical-cable']:
            p=[tuple(map(float,v.split(','))) for v in wire.attrib['d'][1:].split(' L')]
            segments=list(zip(p,p[1:]))
            for a,b in segments:
                for x,y,w,h in boxes:
                    if a[1]==b[1]:
                        self.assertFalse(y<a[1]<y+h and max(min(a[0],b[0]),x)<min(max(a[0],b[0]),x+w))
                    else:
                        self.assertFalse(x<a[0]<x+w and max(min(a[1],b[1]),y)<min(max(a[1],b[1]),y+h))
                for c,d in wires:
                    if a[1]==b[1] and c[0]==d[0]:
                        self.assertFalse(min(a[0],b[0])<c[0]<max(a[0],b[0]) and min(c[1],d[1])<a[1]<max(c[1],d[1]))
                    elif a[0]==b[0] and c[1]==d[1]:
                        self.assertFalse(min(c[0],d[0])<a[0]<max(c[0],d[0]) and min(a[1],b[1])<c[1]<max(a[1],b[1]))
                    elif a[0]==b[0]==c[0]==d[0]:
                        self.assertLessEqual(min(max(a[1],b[1]),max(c[1],d[1]))-max(min(a[1],b[1]),min(c[1],d[1])),0)
                    elif a[1]==b[1]==c[1]==d[1]:
                        self.assertLessEqual(min(max(a[0],b[0]),max(c[0],d[0]))-max(min(a[0],b[0]),min(c[0],d[0])),0)
            wires.extend(segments)

    def test_parallel_and_same_device_cables_have_independent_paths(self):
        m=self.model
        m['l1']['links']=[{'id':'loop','endpoints':['sw01.p1','sw01.p2']}, {'id':'parallel1','endpoints':['pc-a.eth0','gw01.lan']}]
        m['l1']['ports'] += [{'id':'pc-a.extra','device':'pc-a'},{'id':'gw01.extra','device':'gw01'}]
        m['l1']['links'].append({'id':'parallel2','endpoints':['pc-a.extra','gw01.extra']})
        root=ET.fromstring(render(m,layers=['l1']))
        paths=[e.attrib['d'] for e in root.iter() if e.attrib.get('class')=='physical-cable']
        self.assertEqual(len(paths),3)
        self.assertEqual(len(set(paths)),3)
        m['l1']['links']=[]
        root=ET.fromstring(render(m,layers=['l1']))
        self.assertFalse(any('data-cable-id' in e.attrib for e in root.iter()))

    def test_network_groups_have_exact_memberships_and_separate_trunk_anchors(self):
        for layer in ['l2','l3']:
            root=ET.fromstring(render(self.model,layers=[layer]))
            expected=({v['id']:{i['id'] for i in self.model['l2']['interfaces'] if v['id'] in ([i['untagged_vlan']] if i['mode']=='access' else i['tagged_vlans'])} for v in self.model['l2']['vlans']} if layer=='l2' else
                      {s['id']:{i['id'] for i in self.model['l3']['interfaces'] if i['subnet']==s['id']} for s in self.model['l3']['subnets']})
            if layer=='l2':
                expected.update({b['id']:set(b['members']) for b in self.model['l2']['bridges']})
            groups=[e for e in root.iter() if 'data-network-id' in e.attrib]
            self.assertEqual({e.attrib['data-network-id'] for e in groups},set(expected))
            for group in groups:
                identity=group.attrib['data-network-id']
                branches=[e for e in group.iter() if e.attrib.get('class')=='relation-branch']
                self.assertEqual({e.attrib['data-endpoint'] for e in branches},expected[identity])
                self.assertEqual(group.attrib['tabindex'],'0')
                for member in expected[identity]:
                    self.assertIn(member,group.attrib['aria-label'])
                self.assertIn('network-'+next(c[8:] for c in group.attrib['class'].split() if c.startswith('network-l')),root.find('{http://www.w3.org/2000/svg}style').text)
            colors={e.attrib['stroke'] for g in groups if g.attrib['data-network-kind']!='bridge' for e in g.iter() if e.attrib.get('class')=='relation-bus'}
            self.assertEqual(len(colors),2)
            if layer=='l2':
                anchors=[float(e.attrib['cy']) for e in root.iter() if e.attrib.get('data-membership-interface')=='sw01.trunk']
                self.assertEqual(len(anchors),3)
                self.assertEqual(len(set(anchors)),3)

    def test_logical_routes_do_not_share_segments_or_pass_through_equipment(self):
        # Independent geometry checks, including a multi-VLAN trunk and bridge.
        for layer in ['l2','l3']:
            root=ET.fromstring(render(self.model,layers=[layer]))
            boxes=[tuple(float(e.attrib[k]) for k in ('x','y','width','height')) for e in root.iter() if e.attrib.get('class')=='device-frame']
            prior=[]
            for wire in [e for e in root.iter() if e.attrib.get('class') in ('relation-bus','relation-branch')]:
                points=[tuple(map(float,v.split(','))) for v in wire.attrib['d'][1:].split(' L')]
                for a,b in zip(points,points[1:]):
                    for x,y,w,h in boxes:
                        if a[1]==b[1]:
                            self.assertFalse(y<a[1]<y+h and max(min(a[0],b[0]),x)<min(max(a[0],b[0]),x+w))
                        else:
                            self.assertFalse(x<a[0]<x+w and max(min(a[1],b[1]),y)<min(max(a[1],b[1]),y+h))
                    for c,d in prior:
                        for axis in [0,1]:
                            if a[1-axis]==b[1-axis]==c[1-axis]==d[1-axis]:
                                self.assertLessEqual(min(max(a[axis],b[axis]),max(c[axis],d[axis]))-max(min(a[axis],b[axis]),min(c[axis],d[axis])),0)
                        # Near-card departures must not cross another vertical track.
                        if wire.attrib.get('class')=='relation-branch' and a[1]==b[1] and c[0]==d[0]:
                            self.assertFalse(min(a[0],b[0])<c[0]<max(a[0],b[0]) and min(c[1],d[1])<a[1]<max(c[1],d[1]))
                    prior.append((a,b))

    def test_added_empty_network_and_long_membership_labels(self):
        long_id='vlan-'+('long-id-'*9)
        self.model['l2']['vlans'].append({'id':long_id,'tag':30})
        self.model['l2']['interfaces'][-1]['tagged_vlans'].append(long_id)
        self.model['l3']['subnets'].append({'id':'unused-net','cidr':'192.168.99.0/24'})
        root=ET.fromstring(render(self.model))
        added=next(e for e in root.iter() if e.attrib.get('data-network-id')==long_id)
        self.assertEqual([e.attrib['data-endpoint'] for e in added.iter() if e.attrib.get('class')=='relation-branch'],['gw01.trunk'])
        empty=next(e for e in root.iter() if e.attrib.get('data-network-id')=='unused-net')
        self.assertIn('所属インターフェースなし',''.join(empty.itertext()))
        self.assertFalse(any(e.attrib.get('class')=='relation-branch' for e in empty.iter()))
        for card in [e for e in root.iter() if e.attrib.get('class')=='device-card']:
            frame=next(e for e in card if e.attrib.get('class')=='device-frame')
            bottom=float(frame.attrib['y'])+float(frame.attrib['height'])
            for label in [e for e in card.iter() if 'membership-label' in e.attrib.get('class','')]:
                self.assertLess(float(label.attrib['y']),bottom)


if __name__ == '__main__':
    unittest.main()
