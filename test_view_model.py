import copy
import unittest
import yaml
from fastapi.testclient import TestClient
from bench_scale import make_model, encode
from network_model import load_model, validate, ModelError, MAX_YAML_DEPTH, MAX_ELEMENTS
from view_model import prepare_view, ViewScope, TraceRoot, limits
from generate_diagram import render
from web_app import app, render_slots


class ViewTests(unittest.TestCase):
    def test_large_inventory_is_valid_but_unfiltered_drawing_is_blocked(self):
        source=encode(make_model(64,4))
        model,ix=load_model(source,with_index=True)
        projected,display,catalog=prepare_view(model,ix)
        self.assertEqual(len(model['devices']),64)
        self.assertEqual(display['status'],'too_large')
        self.assertEqual(len(catalog['groups']),8)
        with self.assertRaises(ModelError):render(projected)
        result=TestClient(app).post('/api/render',json={'yaml_text':source}).json()
        self.assertEqual(result['svg'],'')
        self.assertEqual(result['counts']['devices'],64)
        self.assertEqual(len(result['devices']),64)
        self.assertEqual(result['display']['status'],'too_large')

    def test_site_and_group_and_device_filters_intersect_without_mutation(self):
        model=make_model(4,2)
        for n,device in enumerate(model['devices']):
            device['location']['site']='本社' if n<2 else '支社'
            device['groups']=['基幹'] if n%2==0 else ['端末']
        original=copy.deepcopy(model)
        ix=validate(model)
        projected,display,catalog=prepare_view(model,ix,ViewScope(site='本社',group='基幹'))
        self.assertEqual([d['id'] for d in projected['devices']],['d000'])
        self.assertEqual(display['status'],'ready')
        self.assertEqual(set(catalog['sites']),{'本社','支社'})
        validate(projected)
        self.assertEqual(model,original)
        empty=prepare_view(model,ix,ViewScope(site='本社',device_ids=['d003']))[1]
        self.assertEqual(empty['status'],'empty')

    def test_boundary_cables_are_reported_and_not_drawn_as_complete_connections(self):
        model=make_model(4,1);ix=validate(model)
        projected,display,_=prepare_view(model,ix,ViewScope(device_ids=['d000']))
        self.assertEqual(projected['l1']['links'],[])
        self.assertEqual(display['boundary_links']['total'],1)
        self.assertEqual(display['boundary_links']['items'][0]['remote_device'],'d001')
        svg=render(projected,context_notes=display['context_notes'])
        self.assertIn('範囲外に接続するケーブル1本',svg)
        self.assertEqual(len(model['l1']['links']),2)

    def test_correspondence_projection_keeps_the_full_component_and_references(self):
        model=make_model(1,7,dense=True);ix=validate(model)
        self.assertEqual(prepare_view(model,ix)[1]['status'],'too_large')
        projected,display,catalog=prepare_view(model,ix,ViewScope(trace_root=TraceRoot(layer='l3',id='d000.ip00')))
        self.assertEqual(display['status'],'ready')
        self.assertEqual(display['counts']['rows'],3)
        self.assertEqual([i['id'] for i in projected['l2']['interfaces']],['d000.eth00'])
        self.assertEqual(len(projected['l2']['vlans']),64)
        self.assertEqual(projected['l2']['bridges'][0]['members'],['d000.eth00'])
        validate(projected);render(projected)
        self.assertEqual(len(catalog['focus_options']),21)

    def test_display_budget_applies_to_the_layer_being_drawn(self):
        model=make_model(8,9);ix=validate(model)
        self.assertEqual(prepare_view(model,ix)[1]['status'],'too_large')
        projected,display,_=prepare_view(model,ix,layers=['l1'])
        self.assertEqual(display['status'],'ready')
        self.assertEqual(display['counts']['rows'],72)
        render(projected,layers=['l1'])

    def test_hidden_invalid_references_are_still_rejected(self):
        model=make_model(32,2)
        model['bindings']['l2_to_l1'][-1]['physical_port']='missing'
        response=TestClient(app).post('/api/render',json={'yaml_text':encode(model),'scope':{'device_ids':['d000']}})
        self.assertEqual(response.status_code,422)
        self.assertNotIn('svg',response.json())

    def test_limits_and_parser_depth_and_busy_responses(self):
        self.assertEqual(TestClient(app).get('/api/limits').json(),limits())
        with self.assertRaises(ModelError):load_model('x: '+('['*(MAX_YAML_DEPTH+1))+'0'+(']'*(MAX_YAML_DEPTH+1)))
        acquired=[]
        try:
            for _ in range(limits()['render_jobs']):acquired.append(render_slots.acquire(blocking=False))
            self.assertTrue(all(acquired))
            result=TestClient(app).post('/api/render',json={'yaml_text':encode(make_model())})
            self.assertEqual(result.status_code,429)
            self.assertEqual(result.headers['retry-after'],'1')
        finally:
            for success in acquired:
                if success:render_slots.release()

    def test_element_limit_is_separate_from_projection_and_device_limits(self):
        model=make_model(256,7,exact_elements=MAX_ELEMENTS)
        load_model(encode(model))
        model['l1']['ports'].append({'id':'one-too-many','device':'d000'})
        with self.assertRaises(ModelError):load_model(encode(model))
        with self.assertRaises(ModelError):load_model(encode(make_model(257,1)))


if __name__=='__main__':unittest.main()
