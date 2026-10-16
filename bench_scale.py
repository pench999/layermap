"""Reproducible synthetic parse/projection/render load checks; no real inventory."""
import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import yaml
from network_model import load_model, ModelError, MAX_YAML_BYTES
from view_model import ViewScope, prepare_view, limits, element_count
from generate_diagram import render


def make_model(devices=4, ports=2, dense=False, long_names=False, exact_elements=None):
    model={'schema':'lan-example/v1','name':'負荷試験用の架空構成','scope':'合成データ・実機ではありません',
           'devices':[],'l1':{'ports':[],'links':[]},'l2':{'vlans':[{'id':'v10','tag':10}],'interfaces':[],'bridges':[]},
           'l3':{'subnets':[],'interfaces':[],'routes':[]},'bindings':{'l2_to_l1':[],'l3_to_l2':[]}}
    if dense:model['l2']['vlans']=[{'id':'v'+str(v),'tag':v} for v in range(10,74)]
    for n in range(devices):
        device=f'd{n:03}'
        model['devices'].append({'id':device,'name':f'Synthetic switch {n:03}','groups':[f'rack-{n//8:02}'],
                                 'location':{'site':f'site-{n//64:02}'},'manufacturer':'Synthetic','model':'Test-only','serial_number':f'FAKE-{n:06}'})
        subnet=f'net{n:03}'
        model['l3']['subnets'].append({'id':subnet,'cidr':f'10.{n//256}.{n%256}.0/24'})
        members=[]
        for p in range(ports):
            physical=f'{device}.p{p:02}';l2=f'{device}.eth{p:02}';l3=f'{device}.ip{p:02}'
            port={'id':physical,'device':device,'name':('長い物理ポート名'*20 if long_names else f'Gi1/0/{p+1}')}
            model['l1']['ports'].append(port)
            interface={'id':l2,'device':device,'mode':'trunk' if dense else 'access'}
            interface.update({'tagged_vlans':['v'+str(v) for v in range(10,74)]} if dense else {'untagged_vlan':'v10'})
            model['l2']['interfaces'].append(interface);members.append(l2)
            model['l3']['interfaces'].append({'id':l3,'device':device,'address':f'10.{n//256}.{n%256}.{p+2}/24','subnet':subnet})
            model['bindings']['l2_to_l1'].append({'l2_interface':l2,'physical_port':physical})
            model['bindings']['l3_to_l2'].append({'l3_interface':l3,'l2_interface':l2,'vlan':'v10'})
        model['l2']['bridges'].append({'id':device+'.bridge','device':device,'members':members})
        if n%2==1 and ports:
            model['l1']['links'].append({'id':f'cable-{n:03}','endpoints':[f'd{n-1:03}.p00',device+'.p00']})
    if exact_elements is not None:
        for n in range(max(0,exact_elements-element_count(model))):
            model['l1']['ports'].append({'id':f'extra-{n}','device':f'd{n%devices:03}'})
    return model


def encode(model):
    return yaml.dump(model,Dumper=getattr(yaml,'CSafeDumper',yaml.SafeDumper),allow_unicode=True,sort_keys=False)


def child(filename, scope):
    source=Path(filename).read_text(encoding='utf-8')
    record={'yaml_bytes':len(source.encode('utf-8'))}
    start=time.perf_counter()
    try:
        model,ix=load_model(source,with_index=True)
        parsed=time.perf_counter()
        projected,display,_=prepare_view(model,ix,ViewScope.model_validate(scope))
        prepared=time.perf_counter()
        svg=render(projected,context_notes=display['context_notes']) if display['status']=='ready' else ''
        done=time.perf_counter()
        record.update(status=display['status'],devices=len(model['devices']),elements=element_count(model),
                      display=display['counts'],parse_ms=round((parsed-start)*1000,2),
                      projection_ms=round((prepared-parsed)*1000,2),render_ms=round((done-prepared)*1000,2),
                      total_ms=round((done-start)*1000,2),svg_bytes=len(svg.encode('utf-8')))
    except ModelError as exc:
        record.update(status='invalid',message=str(exc),total_ms=round((time.perf_counter()-start)*1000,2))
    # VmHWM resets on exec, unlike an inherited ru_maxrss high-water mark.
    status=Path('/proc/self/status').read_text()
    record['process_rss_mib']=round(int(next(line.split()[1] for line in status.splitlines() if line.startswith('VmHWM:')))/1024,2)
    print(json.dumps(record,ensure_ascii=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child');parser.add_argument('--scope',default='{}')
    parser.add_argument('--output',default='/output/scale-benchmark.json')
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--example')
    args=parser.parse_args()
    if args.child:return child(args.child,json.loads(args.scope))
    if args.example:
        Path(args.example).write_text(encode(make_model(64,4)),encoding='utf-8');return
    cases=[('small',make_model(4,2),{}),('view-24-devices',make_model(24,2),{}),
           ('view-168-rows',make_model(8,7),{}),('view-216-rows-blocked',make_model(8,9),{}),
           ('dense-64-vlans',make_model(1,4,dense=True),{}),
           ('dense-over-budget',make_model(1,7,dense=True),{}),
           ('dense-focused',make_model(1,7,dense=True),{'trace_root':{'layer':'l1','id':'d000.p00'}}),
           ('large-whole-blocked',make_model(256,7,exact_elements=10000),{}),
           ('large-group',make_model(256,7,exact_elements=10000),{'group':'rack-00'}),
           ('large-focused',make_model(256,7,exact_elements=10000),{'trace_root':{'layer':'l1','id':'d000.p00'}}),
           ('large-long-names',make_model(256,7,long_names=True),{'device_ids':['d000']}),
           ('over-elements',make_model(256,7,exact_elements=10001),{}),
           ('over-devices',make_model(257,1),{})]
    small=encode(make_model(4,2))
    padding='\n#'+'x'*(MAX_YAML_BYTES-len(small.encode('utf-8'))-2)
    raw_cases=[('exact-yaml-bytes',small+padding,{}),('over-yaml-bytes',small+padding+'x',{})]
    report={'environment':{'python':platform.python_version(),'yaml':yaml.__version__,'libyaml':getattr(yaml,'__with_libyaml__',False),
                           'platform':platform.platform(),'cpu_quota':'1 CPU','memory_limit_mib':512},'limits':limits(),'repeats':args.repeats,'cases':[]}
    with tempfile.TemporaryDirectory(prefix='layermap-bench-') as folder:
        inputs=[]
        for name,model,scope in cases:inputs.append((name,encode(model),scope))
        inputs+=raw_cases
        files={}
        for name,source,scope in inputs:
            filename=Path(folder)/(name+'.yaml');filename.write_text(source,encoding='utf-8');files[name]=(filename,scope)
            runs=[]
            for _ in range(args.repeats):
                started=time.perf_counter()
                process=subprocess.run([sys.executable,__file__,'--child',str(filename),'--scope',json.dumps(scope)],text=True,capture_output=True,check=True)
                run=json.loads(process.stdout);run['wall_ms']=round((time.perf_counter()-started)*1000,2);runs.append(run)
            report['cases'].append({'name':name,'runs':runs,'median_ms':round(statistics.median(r['total_ms'] for r in runs),2),
                                    'max_ms':max(r['total_ms'] for r in runs),'max_rss_mib':max(r['process_rss_mib'] for r in runs)})
        filename,scope=files['large-group']
        start=time.perf_counter()
        jobs=[subprocess.Popen([sys.executable,__file__,'--child',str(filename),'--scope',json.dumps(scope)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
        parallel=[]
        for job in jobs:
            output,error=job.communicate()
            if job.returncode:raise RuntimeError(error)
            parallel.append(json.loads(output))
        report['parallel_two']={'wall_ms':round((time.perf_counter()-start)*1000,2),'runs':parallel}
        peak=Path('/sys/fs/cgroup/memory.peak')
        if peak.exists():report['container_peak_mib']=round(int(peak.read_text())/1048576,2)
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(output),'cases':[{k:v for k,v in c.items() if k!='runs'} for c in report['cases']],
                      'container_peak_mib':report.get('container_peak_mib'),'parallel_two_ms':report['parallel_two']['wall_ms']},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
