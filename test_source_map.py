import copy
import unittest
from pathlib import Path
import yaml
from fastapi.testclient import TestClient
from web_app import app,render_slots
from source_map import SourceRequest,locate_source,MAX_SOURCE_LOCATIONS
from network_model import ModelError
ROOT=Path(__file__).parent
class SourceMapTests(unittest.TestCase):
 def setUp(self):
  self.source=(ROOT/'lan-sample.yaml').read_text(encoding='utf-8');self.model=yaml.safe_load(self.source);self.client=TestClient(app)
 def locate(self,section,id=None,match=None,source=None):return locate_source(SourceRequest(yaml_text=source or self.source,target=dict(section=section,**({'id':id} if id is not None else {}),**({'match':match} if match else {}))))
 def text(self,source,r):return source.encode('utf-16-le')[r['from']*2:r['to']*2].decode('utf-16-le')
 def test_port_definition_incoming_references_and_owner_definition(self):
  p=self.model['l1']['ports'][0];r=self.locate('l1.ports',p['id'])
  self.assertEqual(r['locations'][0]['kind'],'definition');self.assertIn(p['id'],self.text(self.source,r['locations'][0]))
  refs=[l for l in r['locations'] if l['kind']=='reference'];self.assertTrue(any(l['path'].startswith('l1.links') for l in refs));self.assertTrue(any(l['path'].startswith('bindings.l2_to_l1') for l in refs))
  self.assertTrue(all(yaml.safe_load(self.text(self.source,l))==p['id'] for l in refs))
  self.assertTrue(any(l['kind']=='related_definition' and l['path'].startswith('devices') for l in r['locations']))
 def test_id_namespace_and_non_reference_text_are_distinguished(self):
  model=copy.deepcopy(self.model);p=model['l1']['ports'][0]['id'];old=model['l2']['interfaces'][0]['id'];model['l2']['interfaces'][0]['id']=p
  for b in model['bindings']['l2_to_l1']+model['bindings']['l3_to_l2']:
   if b.get('l2_interface')==old:b['l2_interface']=p
  model['notes']=[p];model['devices'][0]['name']=p
  source=yaml.safe_dump(model,allow_unicode=True);r=self.locate('l1.ports',p,source=source)
  paths=[l['path'] for l in r['locations'] if l['kind']=='reference'];self.assertFalse(any(path.endswith('.l2_interface') for path in paths));self.assertFalse(any('notes' in path or 'name' in path for path in paths))
  r=self.locate('l2.interfaces',p,source=source);self.assertTrue(any(l['path'].endswith('.l2_interface') for l in r['locations']))
 def test_binding_selected_by_endpoints_not_projected_map_number(self):
  b=self.model['bindings']['l3_to_l2'][-1];match={k:b[k] for k in ['l3_interface','l2_interface']}
  r=self.locate('bindings.l3_to_l2',match=match)
  self.assertEqual(yaml.safe_load(self.text(self.source,r['locations'][0])),b)
  self.assertEqual(len([l for l in r['locations'] if l['kind']=='related_definition']),3)
 def test_utf16_offsets_crlf_cr_unicode_and_quotes(self):
  p=self.model['l1']['ports'][0]['id']
  for eol in ['\n','\r\n','\r']:
   source=('# 😀日本語\n'+self.source).replace('\n',eol);r=self.locate('l1.ports',p,source=source)
   for l in r['locations']:
    text=self.text(source,l);self.assertTrue(text);self.assertEqual(source[:len(source.encode('utf-16-le')[:l['from']*2].decode('utf-16-le'))].count(eol)+1,l['line'])
   self.assertEqual(yaml.safe_load(self.text(source,r['locations'][0]))['id'],p)
 def test_block_ranges_exclude_following_comments_and_flow_records_are_exact(self):
  model=copy.deepcopy(self.model);source=yaml.safe_dump(model,allow_unicode=True,sort_keys=False)
  source=source.replace('- id: pc-b',' # following record comment\n- id: pc-b',1)
  r=self.locate('devices',model['devices'][0]['id'],source=source)
  self.assertNotIn('following record comment',self.text(source,r['locations'][0]))
  source=yaml.safe_dump(model,allow_unicode=True,default_flow_style=True);r=self.locate('devices',model['devices'][0]['id'],source=source)
  self.assertEqual(yaml.safe_load(self.text(source,r['locations'][0])),model['devices'][0])
 def test_vpn_network_and_connection_targets(self):
  from vpn_model import VpnRequest,preview_vpn
  s=self.client.get('/api/vpn/sample').json();source=preview_vpn(VpnRequest(**{k:s[k] for k in ['yaml_text','connections_yaml']}))['yaml_text']
  r=self.locate('vpn_connections','vpn-office',source=source);self.assertEqual(len([l for l in r['locations'] if l['kind']=='related_definition']),4)
  r=self.locate('l3.subnets','hq::net-office',source=source);self.assertTrue(any(l['path'].startswith('vpn_connections') and l['kind']=='reference' for l in r['locations']))
  source=(ROOT/'samples/04-wired-wifi-status.yaml').read_text(encoding='utf-8');connection=yaml.safe_load(source)['l1']['connections'][0]
  r=self.locate('l1.connections',connection['id'],source=source);self.assertEqual(yaml.safe_load(self.text(source,r['locations'][0]))['id'],connection['id'])
 def test_reference_limit_is_explicit_and_retains_primary_definition(self):
  model=copy.deepcopy(self.model);i=next(i for i in model['l2']['interfaces'] if i['device']=='sw01')
  model['l2']['bridges'] += [dict(id='many'+str(n),device='sw01',members=[i['id']]*128) for n in range(10)]
  source=yaml.safe_dump(model,allow_unicode=True);r=self.locate('l2.interfaces',i['id'],source=source)
  self.assertTrue(r['truncated']);self.assertGreater(r['total'],MAX_SOURCE_LOCATIONS);self.assertEqual(len(r['locations']),MAX_SOURCE_LOCATIONS);self.assertEqual(r['locations'][0]['kind'],'definition')
 def test_api_validation_unknown_targets_and_shared_busy_limit(self):
  body=dict(yaml_text=self.source,target=dict(section='devices',id='pc-a'))
  r=self.client.post('/api/source/locate',json=body);self.assertEqual(r.status_code,200)
  for target in [dict(section='devices',id='missing'),dict(section='notes',id='x'),dict(section='devices',id='pc-a',match={'x':'y'}),dict(section='bindings.l2_to_l1',id='x')]:
   self.assertEqual(self.client.post('/api/source/locate',json=dict(body,target=target)).status_code,422)
  self.assertEqual(self.client.post('/api/source/locate',json=dict(body,yaml_text='bad: [')).status_code,422)
  render_slots.acquire();render_slots.acquire()
  try:self.assertEqual(self.client.post('/api/source/locate',json=body).status_code,429)
  finally:render_slots.release();render_slots.release()
if __name__=='__main__':unittest.main()
