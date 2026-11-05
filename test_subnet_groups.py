import copy
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
import yaml
from network_model import validate,load_model,ModelError
from generate_diagram import render
from view_model import prepare_view,ViewScope,display_stats,element_count
from merge_model import merge_preview,MergeRequest
from source_map import locate_source,SourceRequest

class SubnetGroupTests(unittest.TestCase):
    def setUp(self):
        self.source=Path('samples/13-subnet-groups.yaml').read_text()
        self.model=load_model(self.source)

    def test_invalid_membership_does_not_weaken_ip_and_cidr_validation(self):
        for members in [[],['missing'],['service-a','service-a']]:
            model=copy.deepcopy(self.model);model['l3']['subnet_groups'][0]['members']=members
            with self.assertRaises(ModelError):validate(model)
        for duplicate in [dict(id='other',members=['service-a']),dict(id='service-networks',members=['management'])]:
            model=copy.deepcopy(self.model);model['l3']['subnet_groups'].append(duplicate)
            with self.assertRaises(ModelError):validate(model)
        model=copy.deepcopy(self.model);model['l3']['interfaces'][0]['address']='198.51.100.10/24'
        with self.assertRaises(ModelError):validate(model)
        model=copy.deepcopy(self.model);model['l3']['subnets'][0]['cidr']=['192.0.2.0/24','198.51.100.0/24']
        with self.assertRaises(ModelError):validate(model)

    def test_one_outer_frame_preserves_cidrs_endpoints_and_ungrouped_subnet(self):
        root=ET.fromstring(render(self.model,layers=['l3']))
        groups=[e for e in root.iter() if e.get('data-subnet-group-id')]
        self.assertEqual(len(groups),1)
        frames=[e for e in root.iter() if e.get('class')=='subnet-display-frame']
        self.assertEqual(len(frames),1)
        nets=[e for e in root.iter() if e.get('data-network-kind')=='subnet']
        self.assertEqual({e.get('data-network-id') for e in nets},{s['id'] for s in self.model['l3']['subnets']})
        self.assertEqual(len([e for e in root.iter() if e.get('data-element-id')]),4)
        for cidr in ['192.0.2.0/24','198.51.100.0/24','2001:db8:100::/64']:self.assertIn(cidr,''.join(root.itertext()))
        frame=frames[0];top=float(frame.get('y'));bottom=top+float(frame.get('height'))
        for n in nets:
            ys=[float(e.get('y')) for e in n if e.tag.endswith('text')]
            if n.get('data-network-id')=='management':self.assertGreater(min(ys),bottom)
            else:self.assertTrue(all(top<y<bottom for y in ys))

    def test_projection_and_budgets_keep_only_visible_members(self):
        ix=validate(self.model)
        projected,meta,_=prepare_view(self.model,ix,ViewScope(device_ids=['app-b']))
        self.assertEqual(projected['l3']['subnet_groups'][0]['members'],['service-b'])
        validate(projected)
        projected,_,_=prepare_view(self.model,ix,ViewScope(device_ids=['admin']))
        self.assertEqual(projected['l3']['subnet_groups'],[])
        self.assertEqual(display_stats(self.model,['l3'])['groups'],2)
        plain=copy.deepcopy(self.model);plain['l3'].pop('subnet_groups')
        self.assertEqual(element_count(self.model)-element_count(plain),4)
        validate(plain)

    def test_merge_namespaces_group_and_member_ids_and_retains_overlap_checks(self):
        request=MergeRequest(sources=[dict(site_id=s,filename=s+'.yaml',yaml_text=self.source) for s in ['hq','branch']])
        result=merge_preview(request);merged=load_model(result['yaml_text'])
        groups=merged['l3']['subnet_groups']
        self.assertEqual([g['id'] for g in groups],['hq::service-networks','branch::service-networks'])
        self.assertEqual(groups[0]['members'],['hq::service-a','hq::service-b','hq::service-v6'])
        self.assertTrue(any(i['kind']=='overlapping_subnets' for i in result['issues']))

    def test_source_maps_group_members_and_reverse_references(self):
        group=locate_source(SourceRequest(yaml_text=self.source,target=dict(section='l3.subnet_groups',id='service-networks')))
        self.assertTrue(any('l3.subnet_groups[0]' in l['path'] for l in group['locations']))
        self.assertTrue(any('l3.subnets[0]' in l['path'] for l in group['locations']))
        subnet=locate_source(SourceRequest(yaml_text=self.source,target=dict(section='l3.subnets',id='service-a')))
        self.assertTrue(any('members[0]' in l['path'] for l in subnet['locations']))
