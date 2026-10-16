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
                    self.assertEqual(float(first.split(',')[1]), nodes[(layer.attrib['data-layer'],branch.attrib['data-endpoint'])])
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


if __name__ == '__main__':
    unittest.main()
