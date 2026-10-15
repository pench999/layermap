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


if __name__ == '__main__':
    unittest.main()
