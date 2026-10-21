"""Shared VLAN definitions remain distinct from devices and numeric tags."""
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
import yaml
from generate_diagram import render

class SharedVlanTests(unittest.TestCase):
    def setUp(self):
        self.model = yaml.safe_load(Path('lan-sample.yaml').read_text())

    def test_shared_frames_keep_device_rows_trunks_and_binding_endpoints(self):
        root = ET.fromstring(render(self.model))
        networks = [e for e in root.iter() if e.get('data-network-kind') == 'vlan']
        self.assertEqual({e.get('data-network-id') for e in networks}, {'vlan-office', 'vlan-guest'})
        self.assertEqual(len(networks), 2)
        for net in networks:
            frames = [e for e in net if 'vlan-frame' in e.get('class', '').split()]
            self.assertEqual(len(frames), 1)
            frame = frames[0]
            members = {e.get('data-endpoint') for e in net if e.get('class') == 'relation-branch'}
            self.assertIn('sw01.trunk', members)
            self.assertIn('gw01.trunk', members)
            self.assertIn('pc-a.l2' if net.get('data-network-id') == 'vlan-office' else 'pc-b.l2', members)
            bottom = float(frame.get('y')) + float(frame.get('height'))
            for branch in [e for e in net if e.get('class') == 'relation-branch']:
                y = float(branch.get('d').split(' L')[-1].split(',')[-1])
                self.assertLess(float(frame.get('y')), y)
                self.assertLess(y, bottom)
        rows = [e for e in root.iter() if 'interface-row' in e.get('class', '').split()]
        expected = sum(len(self.model[layer][key]) for layer, key in [('l1','ports'),('l2','interfaces'),('l3','interfaces')])
        self.assertEqual(len(rows), expected)
        self.assertEqual(len([e for e in root.iter() if e.get('class') == 'binding-edge']), sum(map(len,self.model['bindings'].values())))

    def test_equal_tags_and_empty_vlan_do_not_merge_definition_ids(self):
        self.model['l2']['vlans'][1]['tag'] = 10
        self.model['l2']['vlans'].append({'id':'empty<&', 'tag':10, 'label':'未接続<&'})
        root = ET.fromstring(render(self.model, layers=['l2'], show_bindings=False))
        nets = [e for e in root.iter() if e.get('data-network-kind') == 'vlan']
        self.assertEqual(len(nets),3)
        empty = next(e for e in nets if e.get('data-network-id') == 'empty<&')
        self.assertIn('所属インターフェースなし', ''.join(empty.itertext()))
        self.assertEqual(len([e for e in root.iter() if e.get('class') == 'network-frame vlan-frame']),3)
        self.assertFalse(any(e.get('data-binding') for e in root.iter()))
