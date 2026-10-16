import json
from pathlib import Path
import unittest
import yaml
from fastapi.testclient import TestClient
from input_support import DeviceOperation, ConnectionOperation, preview, catalog
from network_model import load_model,ModelError
from web_app import app,render_slots

SOURCE=Path(__file__).with_name('lan-sample.yaml').read_text(encoding='utf-8')

def op(**values):
    return DeviceOperation(type='device',device={'id':'new-pc','role':'endpoint','name':'新PC😀','serial_number':'SN-001'},vlans=['vlan-office'],address='192.168.10.50/24',subnet='net-office',ip_vlan='vlan-office',gateway='192.168.10.1',**values)

class InputSupportTests(unittest.TestCase):
    def assert_additive(self,source,operation):
        result=preview(source,operation)
        # Browser offsets count UTF-16 code units, including emoji and CRLF.
        raw=result['yaml_text'].encode('utf-16-le')
        positions=[];delta=0
        for e in result['changes']:
            start=(e['from']+delta)*2
            positions.append((e,start));delta+=len(e['insert'].encode('utf-16-le'))//2-(e['to']-e['from'])
        for e,start in reversed(positions):
            end=start+len(e['insert'].encode('utf-16-le'))
            self.assertEqual(raw[start:end],e['insert'].encode('utf-16-le'))
            raw=raw[:start]+raw[end:]
        self.assertEqual(raw.decode('utf-16-le'),source)
        model=load_model(result['yaml_text'])
        return result,model

    def test_block_comments_crlf_quotes_and_unicode_are_preserved(self):
        source='# 😀 manual header\r\n'+SOURCE.replace('\n','\r\n').replace('schema: lan-example/v1','schema: "lan-example/v1" # keep this')+'# trailing comment\r\n'
        result,model=self.assert_additive(source,op())
        self.assertEqual(len(model['devices']),5)
        self.assertIn('# keep this',result['yaml_text'])
        self.assertEqual(len(model['bindings']['l3_to_l2']),5)
        self.assertEqual(len(model['l3']['routes']),3)
        self.assertNotIn('\n',result['yaml_text'].replace('\r\n',''))

    def test_flow_root_trailing_commas_and_document_end(self):
        data=yaml.safe_load(SOURCE)
        for source in [json.dumps(data,ensure_ascii=False),json.dumps(data,ensure_ascii=False)[:-1]+',}',SOURCE.rstrip()+'\n...\n# end']:
            self.assert_additive(source,op())

    def test_empty_flow_lists_missing_connections_and_routes(self):
        data=yaml.safe_load(SOURCE);data['l3'].pop('routes');data['l3']['interfaces']=[];data['bindings']['l3_to_l2']=[]
        source=yaml.safe_dump(data,allow_unicode=True,sort_keys=False)
        self.assert_additive(source,op())
        # Optional connections is absent from legacy YAML.
        connection=ConnectionOperation(type='connection',connection={'id':'unknown','kind':'wired','status':'port_unknown','endpoints':[{'port':'new-pc.eth0'},{'device':'sw01'}]})
        candidate=preview(SOURCE,op())['yaml_text']
        result,model=self.assert_additive(candidate,connection)
        self.assertEqual(model['l1']['connections'][0]['status'],'port_unknown')
        self.assertIn('connections:',result['yaml_text'])

    def test_ap_trunk_switch_and_l1_only(self):
        for role in ['l2-switch','access-point','internet-gateway']:
            operation=DeviceOperation(type='device',device={'id':'new','role':role},port_count=3,mode='trunk',vlans=['vlan-office','vlan-guest'])
            result,model=self.assert_additive(SOURCE,operation)
            self.assertEqual(len(model['l1']['ports']),6+(2 if role=='access-point' else 3))
        _,model=self.assert_additive(SOURCE,DeviceOperation(type='device',device={'id':'wifi','role':'endpoint'},port_kind='wifi',configure_l2=False))
        self.assertEqual(model['l1']['ports'][-1]['kind'],'wifi')

    def test_invalid_operation_never_changes_source(self):
        with self.assertRaises(ModelError):preview(SOURCE,DeviceOperation(type='device',device={'id':'pc-a','role':'endpoint'},configure_l2=False))
        with self.assertRaises(ModelError):preview(SOURCE,DeviceOperation(type='device',device={'id':'new','role':'endpoint'},vlans=['missing']))
        with self.assertRaises(ModelError):preview(SOURCE,ConnectionOperation(type='connection',connection={'id':'occupied','kind':'wired','status':'confirmed','endpoints':[{'port':'pc-a.eth0'},{'port':'sw01.p2'}]}))
        with self.assertRaises(ModelError):preview(SOURCE,DeviceOperation(type='device',device={'id':'bad-wifi','role':'endpoint'},port_kind='wifi',mode='trunk',vlans=['vlan-office','vlan-guest']))
        self.assertTrue(all(p['occupied'] for p in catalog(SOURCE)['ports']))

    def test_api_validation_and_shared_concurrency_limit(self):
        client=TestClient(app)
        self.assertEqual(client.post('/api/assist/catalog',json={'yaml_text':SOURCE}).status_code,200)
        response=client.post('/api/assist/preview',json={'yaml_text':SOURCE,'operation':op().model_dump()})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(client.post('/api/assist/preview',json={'yaml_text':SOURCE,'operation':{'type':'bad'}}).status_code,422)
        self.assertEqual(client.post('/api/assist/catalog',json={'yaml_text':'invalid'}).status_code,422)
        self.assertEqual(client.post('/api/assist/preview',json={'yaml_text':SOURCE,'operation':op().model_dump(),'extra':True}).status_code,422)
        acquired=0
        try:
            while render_slots.acquire(blocking=False):acquired+=1
            self.assertEqual(client.post('/api/assist/catalog',json={'yaml_text':SOURCE}).status_code,429)
        finally:
            for _ in range(acquired):render_slots.release()

if __name__=='__main__':unittest.main()
