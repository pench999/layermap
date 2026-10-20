import copy,json
from pathlib import Path
import unittest
import yaml
from fastapi.testclient import TestClient
from merge_model import MergeSource,MergeRequest,merge_preview
from network_model import load_model,ModelError
from view_model import prepare_view,ViewScope,TraceRoot
from generate_diagram import render
from web_app import app,render_slots

ROOT=Path(__file__).parent
HQ=(ROOT/'samples/06-merge-hq.yaml').read_text(encoding='utf-8')
OSAKA=(ROOT/'samples/07-merge-osaka.yaml').read_text(encoding='utf-8')
def request(a=HQ,b=OSAKA):return MergeRequest(sources=[MergeSource(site_id='hq',filename='hq.yaml',yaml_text=a),MergeSource(site_id='osaka',filename='osaka.yaml',yaml_text=b)])
def empty(count=1,ports=0):
 return {'schema':'lan-example/v1','devices':[{'id':'d'+str(n)} for n in range(count)],'l1':{'ports':[{'id':'p'+str(n),'device':'d0'} for n in range(ports)],'links':[]},'l2':{'vlans':[],'interfaces':[],'bridges':[]},'l3':{'subnets':[],'interfaces':[]},'bindings':{'l2_to_l1':[],'l3_to_l2':[]}}

class MergeTests(unittest.TestCase):
 def test_every_reference_including_svi_bridges_and_routes_is_namespaced(self):
  req=request();before=[s.yaml_text for s in req.sources];result=merge_preview(req);m,ix=load_model(result['yaml_text'],with_index=True)
  self.assertEqual([s.yaml_text for s in req.sources],before)
  self.assertEqual(len(m['devices']),8);self.assertEqual(len(m['l1']['links']),6)
  self.assertEqual(ix['l2.interfaces']['hq::sw01.svi99']['vlan'],'hq::vlan-management')
  self.assertIn('hq::sw01.svi99',ix['l2.bridges']['hq::sw01.bridge']['members'])
  self.assertTrue(all(d['location']['site']==d['id'].split('::')[0] for d in m['devices']))
  self.assertTrue(all(b['l3_interface'].split('::')[0]==b['l2_interface'].split('::')[0]==b['vlan'].split('::')[0] for b in m['bindings']['l3_to_l2']))
  self.assertEqual(ix['l3.interfaces']['hq::sw01.management']['address'],'192.168.99.2/24')
  self.assertEqual(ix['l2.vlans']['osaka::vlan-office']['tag'],10)
  self.assertEqual(ix['devices']['hq::sw01']['groups'],['ネットワーク機器'])
  self.assertEqual(m['l3']['routes'][0]['interface'],'hq::sw01.management')
  self.assertTrue(result['id_collisions']>0)
  self.assertEqual(result['mapping'][0],dict(site_id='hq',section='devices',original='pc-a',converted='hq::pc-a'))
  self.assertEqual(result['sources'][0]['previous_sites'],['本社'])

 def test_overlap_and_duplicate_addresses_are_reports_not_automatic_connections(self):
  result=merge_preview(request());kinds={i['kind'] for i in result['issues']}
  self.assertTrue({'duplicate_ip','overlapping_subnets','same_vlan_tag'}<=kinds)
  m,ix=load_model(result['yaml_text'],with_index=True)
  projected,display,_=prepare_view(m,ix,ViewScope(site='hq'))
  self.assertEqual(len(projected['devices']),4);self.assertEqual(display['boundary_links']['total'],0)
  self.assertEqual(len(projected['l2']['vlans']),3);render(projected)
  focus,_,_=prepare_view(m,ix,ViewScope(trace_root=TraceRoot(layer='l2',id='hq::sw01.svi99')))
  self.assertEqual(len(focus['l1']['ports']),0);self.assertEqual(len(focus['l3']['interfaces']),1)
  self.assertTrue(all(d['id'].startswith('hq::') for d in focus['devices']))

 def test_uncertain_and_wifi_connections_transform_only_known_endpoints(self):
  source=(ROOT/'samples/04-wired-wifi-status.yaml').read_text(encoding='utf-8');r=merge_preview(request(source,source));m=load_model(r['yaml_text'])
  connections=m['l1']['connections'];self.assertEqual(len(connections),12)
  for c in connections:
   for e in c['endpoints']:
    if 'unknown' in e:self.assertEqual(e,{'unknown':True})
    else:self.assertTrue(next(iter(e.values())).startswith(c['id'].split('::')[0]+'::'))
  self.assertTrue(any(c.get('ssid')=='LayerMap-Office' for c in connections))

 def test_repeated_device_metadata_is_reported_and_preserved(self):
  result=merge_preview(request(HQ,HQ));kinds={i['kind'] for i in result['issues']}
  self.assertIn('duplicate_serial',kinds);self.assertIn('duplicate_name',kinds)
  m=load_model(result['yaml_text']);self.assertEqual(m['devices'][0]['serial_number'],m['devices'][4]['serial_number'])

 def test_duplicate_sites_bad_site_ids_long_ids_and_invalid_sources_are_rejected(self):
  for sites in [('hq','hq'),('HQ','osaka'),('hq::x','osaka')]:
   r=request();r.sources[0].site_id=sites[0];r.sources[1].site_id=sites[1]
   with self.assertRaises(ModelError):merge_preview(r)
  m=empty();m['devices'][0]['id']='x'*100
  with self.assertRaisesRegex(ModelError,'100文字'):merge_preview(request(yaml.safe_dump(m),OSAKA))
  bad=HQ.replace('physical_port: sw01.p1','physical_port: missing')
  with self.assertRaises(ModelError) as ctx:merge_preview(request(bad,OSAKA))
  self.assertIn('hq.yaml',str(ctx.exception));self.assertIn('sources[0]',ctx.exception.path);self.assertIsNotNone(ctx.exception.line)
  with self.assertRaises(ModelError):merge_preview(request('schema: x\nschema: y',OSAKA))

 def test_limits_apply_to_the_combined_model(self):
  valid=yaml.safe_dump(empty(count=128));self.assertEqual(merge_preview(request(valid,valid))['counts']['devices'],256)
  too_many=yaml.safe_dump(empty(count=129))
  with self.assertRaises(ModelError):merge_preview(request(too_many,too_many))
  ports=yaml.safe_dump(empty(ports=5000))
  with self.assertRaises(ModelError):merge_preview(request(ports,ports))
  huge=HQ+'#'+('x'*1100000)
  with self.assertRaisesRegex(ModelError,'合計'):merge_preview(request(huge,huge))

 def test_prefix_is_unambiguous_and_notes_survive_in_header_when_not_displayed(self):
  m=empty();m['devices'][0]['id']='hq::node';m['notes']=['a'*500]*20
  s=yaml.safe_dump(m);r=merge_preview(request(s,s));parsed=load_model(r['yaml_text'])
  self.assertEqual(parsed['devices'][0]['id'],'hq::hq::node');self.assertEqual(parsed['devices'][1]['id'],'osaka::hq::node')
  self.assertIn('a'*500,r['yaml_text']);self.assertTrue(any(i['kind']=='notes_display_limit' for i in r['issues']))
  self.assertLessEqual(len(parsed['notes']),20)

 def test_advisory_report_is_bounded_without_skipping_validation(self):
  m=empty(count=256)
  for n,d in enumerate(m['devices']):d['name']='dup'+str(n//2);d['serial_number']='serial'+str(n//2)
  s=yaml.safe_dump(m);other=yaml.safe_dump(empty())
  # Keep the whole model at 256 devices.
  m['devices'].pop();s=yaml.safe_dump(m)
  r=merge_preview(request(s,other));self.assertTrue(r['issues_truncated']);self.assertEqual(len(r['issues']),200)
  self.assertTrue(all(len(i['items'])<=30 for i in r['issues']))

 def test_ipv6_and_nested_ranges_do_not_join_disjoint_ipv4_ranges(self):
  m=empty();m['l2']={'vlans':[{'id':'v','tag':10}],'interfaces':[{'id':'svi','device':'d0','mode':'svi','vlan':'v'}],'bridges':[{'id':'bridge','device':'d0','members':['svi']}]}
  m['l3']={'subnets':[{'id':'net6','cidr':'2001:db8::/64'},{'id':'nested','cidr':'2001:db8::/80'}],'interfaces':[{'id':'ip6','device':'d0','address':'2001:db8::2/64','subnet':'net6'}],'routes':[{'device':'d0','destination':'::/0','next_hop':'2001:db8::1','interface':'ip6'}]}
  m['bindings']['l3_to_l2']=[{'l3_interface':'ip6','l2_interface':'svi','vlan':'v'}]
  other=copy.deepcopy(m);other['l3']['interfaces'][0]['address']='2001:DB8::2/64'
  other['l3']['subnets']+=[{'id':'half1','cidr':'192.0.2.0/25'},{'id':'half2','cidr':'192.0.2.128/25'}]
  r=merge_preview(request(yaml.safe_dump(m),yaml.safe_dump(other)));load_model(r['yaml_text'])
  overlaps=[i for i in r['issues'] if i['kind']=='overlapping_subnets']
  self.assertEqual(len(overlaps),1);self.assertEqual(overlaps[0]['total'],4)
  self.assertTrue(any(i['kind']=='duplicate_ip' and '2001:db8::2' in i['message'] for i in r['issues']))

 def test_api_samples_validation_and_shared_busy_limit(self):
  client=TestClient(app);r=client.get('/api/merge/sample');self.assertEqual(r.status_code,200)
  response=client.post('/api/merge/preview',json=r.json());self.assertEqual(response.status_code,200,response.text)
  self.assertEqual(client.post('/api/merge/preview',json={'sources':[]}).status_code,422)
  self.assertEqual(client.post('/api/merge/preview',json={'sources':r.json()['sources']*9}).status_code,422)
  acquired=0
  try:
   while render_slots.acquire(blocking=False):acquired+=1
   self.assertEqual(client.post('/api/merge/preview',json=r.json()).status_code,429)
  finally:
   for _ in range(acquired):render_slots.release()

if __name__=='__main__':unittest.main()
