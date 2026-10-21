"""48-port capacity study with isolated candidate limits; synthetic inventory only."""
import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import view_model
from bench_scale import make_model,encode,child
from network_model import load_model
from view_model import element_count,limits

CANDIDATE={'view_rows':600,'view_connections':1200,'view_elements':1600,'svg_bytes':8*1024*1024}

def make_48port_model(hosts=12):
    if not 1<=hosts<=21:raise ValueError('1..21 synthetic hosts')
    m={'schema':'lan-example/v1','name':'48ポートスイッチ3台＋接続先の負荷試験','scope':'架空構成。実機の設定・アドレスではありません。',
       'devices':[],'l1':{'ports':[],'links':[],'connections':[]},
       'l2':{'vlans':[dict(id='v'+str(v),tag=v,label=label) for v,label in [(1,'管理'),(10,'検証'),(100,'サービス'),(200,'業務')]],'interfaces':[],'bridges':[]},
       'l3':{'subnets':[dict(id='net'+str(v),cidr='10.48.'+str(v)+'.0/24') for v in [1,100,200]],'interfaces':[],'routes':[]},
       'bindings':{'l2_to_l1':[],'l3_to_l2':[]},'notes':['48ポート×3台をすべてL1/L2に登録。3台のSVIと接続先ホストも表示。','未使用ポートも保持。VLAN10はスイッチ間trunkのみに定義。LACPや到達性は推定しません。']}
    def device(identity,role,groups):
        m['devices'].append(dict(id=identity,name=identity.upper(),role=role,manufacturer='Synthetic',model='Load-test only',serial_number='FAKE-'+identity,groups=groups,location={'site':'負荷試験拠点','rack':'R1'}))
    def port(identity,owner,name):m['l1']['ports'].append(dict(id=identity,device=owner,name=name,kind='wired'))
    def iface(identity,owner,physical,vlan=None,trunk=False,aggregation=None):
        i=dict(id=identity,device=owner,mode='trunk' if trunk else 'access')
        i.update(tagged_vlans=['v1','v10','v100','v200']) if trunk else i.update(untagged_vlan='v'+str(vlan))
        if aggregation:i['aggregation']=aggregation
        m['l2']['interfaces'].append(i)
        for p in physical:m['bindings']['l2_to_l1'].append(dict(l2_interface=identity,physical_port=p))
    def ip(identity,owner,address,vlan,lower):
        m['l3']['interfaces'].append(dict(id=identity,device=owner,address=address,subnet='net'+str(vlan)))
        m['bindings']['l3_to_l2'].append(dict(l3_interface=identity,l2_interface=lower,vlan='v'+str(vlan)))
    for n in [1,2,3]:
        d='sw'+str(n).zfill(2);device(d,'l2-switch',['switches','48-port']);members=[]
        for p in range(1,49):
            pid=d+'.p'+str(p).zfill(2);iid=pid+'.l2';port(pid,d,'Gi1/0/'+str(p))
            trunk=(n==1 and p==47) or (n==2 and p==48) or (n==3 and p in [47,48])
            vlan=100 if n in [1,2] and p<=hosts else (1 if p%2 else 200) if n==3 and p<=2*hosts else 1
            iface(iid,d,[pid],vlan,trunk);members.append(iid)
        svi=d+'.svi1';m['l2']['interfaces'].append(dict(id=svi,device=d,mode='svi',vlan='v1'));members.append(svi)
        m['l2']['bridges'].append(dict(id=d+'.bridge',device=d,members=members));ip(d+'.management',d,'10.48.1.'+str(n+1)+'/24',1,svi)
    for n in range(hosts):
        d='host'+str(n+1).zfill(2);device(d,'endpoint',['hosts'])
        for p in range(4):port(d+'.eth'+str(p),d,'Ethernet'+str(p))
        iface(d+'.bond0',d,[d+'.eth0',d+'.eth1'],100,aggregation={'kind':'bond','mode':'active_backup','primary_port':d+'.eth0'})
        iface(d+'.management',d,[d+'.eth2'],1);iface(d+'.business',d,[d+'.eth3'],200)
        for vlan,lower in [(100,d+'.bond0'),(1,d+'.management'),(200,d+'.business')]:ip(d+'.ip'+str(vlan),d,'10.48.'+str(vlan)+'.'+str(n+20)+'/24',vlan,lower)
        for p,switch,sp in [(0,1,n+1),(1,2,n+1),(2,3,2*n+1),(3,3,2*n+2)]:
            m['l1']['links'].append(dict(id=d+'-cable'+str(p),endpoints=[d+'.eth'+str(p),'sw'+str(switch).zfill(2)+'.p'+str(sp).zfill(2)],medium='copper',speed='1Gbps'))
    for n,p in [(1,47),(2,48)]:m['l1']['links'].append(dict(id='uplink-'+str(n),endpoints=['sw'+str(n).zfill(2)+'.p'+str(p),'sw03.p'+str(p)],medium='fiber',speed='10Gbps'))
    return m

def long_reference_model():
    m=make_model(20,10,long_names=True);renames={}
    def collect(value):
        if isinstance(value,dict):
            if 'id' in value:renames[value['id']]=value['id']+'-'+'x'*(99-len(value['id']))
            for item in value.values():collect(item)
        elif isinstance(value,list):
            for item in value:collect(item)
    def convert(value):
        if isinstance(value,dict):return {k:convert(v) for k,v in value.items()}
        if isinstance(value,list):return [convert(v) for v in value]
        return renames.get(value,value) if isinstance(value,str) else value
    collect(m);return convert(m)

def cases():
    edge=make_model(20,10);over=make_model(20,10);over['l1']['ports'].append(dict(id='extra-row',device='d000'))
    many=make_model(1,1)
    many['l3']['routes']=[dict(device='d000',destination='10.255.0.0/16',next_hop='10.0.0.1',interface='d000.ip00') for _ in range(1600-element_count(many))]
    more=json.loads(json.dumps(many));more['l3']['routes'].append(dict(more['l3']['routes'][0]))
    return [('three-48-switches-12-hosts',make_48port_model(),{}),('three-48-switches-21-hosts',make_48port_model(21),{}),
      ('three-48-single-switch',make_48port_model(),{'device_ids':['sw01']}),
      ('rows-600',edge,{}),('rows-601',over,{}),('rows-600-long-labels',make_model(20,10,long_names=True),{}),('rows-600-long-ids-and-labels',long_reference_model(),{}),
      ('dense-17-ports-64-vlans',make_model(1,17,dense=True),{}),('dense-18-ports-64-vlans',make_model(1,18,dense=True),{}),
      ('elements-1600',many,{}),('elements-1601',more,{})]

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--child');parser.add_argument('--scope',default='{}')
    parser.add_argument('--candidate',action='store_true');parser.add_argument('--output',default='/output/48port-benchmark.json')
    parser.add_argument('--only');parser.add_argument('--repeats',type=int,default=3);parser.add_argument('--example');args=parser.parse_args()
    if args.example:
        value=encode(make_48port_model())
        if args.example=='-':print(value,end='')
        else:Path(args.example).write_text(value,encoding='utf-8')
        return
    if args.candidate:
        for key,value in CANDIDATE.items():setattr(view_model,'MAX_'+key.upper(),value)
    if args.child:return child(args.child,json.loads(args.scope))
    report={'limits':limits(),'candidate':args.candidate,'environment':{'cpu_quota':'1 CPU','memory_limit_mib':512},'repeats':args.repeats,'cases':[]}
    with tempfile.TemporaryDirectory() as directory:
        files={}
        for name,m,scope in cases():
            if args.only and name!=args.only:continue
            file=Path(directory)/(name+'.yaml');file.write_text(encode(m),encoding='utf-8');files[name]=(file,scope);runs=[]
            for _ in range(args.repeats):
                command=[sys.executable,__file__,'--child',str(file),'--scope',json.dumps(scope)]+(['--candidate'] if args.candidate else [])
                process=subprocess.run(command,capture_output=True,text=True,check=True,timeout=120)
                runs.append(json.loads(process.stdout))
            report['cases'].append(dict(name=name,runs=runs,median_ms=round(statistics.median(r['total_ms'] for r in runs),2),max_ms=max(r['total_ms'] for r in runs),max_rss_mib=max(r['process_rss_mib'] for r in runs)))
        file,scope=files.get('three-48-switches-12-hosts',next(iter(files.values())))
        start=time.perf_counter();command=[sys.executable,__file__,'--child',str(file),'--scope',json.dumps(scope)]+(['--candidate'] if args.candidate else [])
        jobs=[subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)];parallel=[]
        for job in jobs:
            stdout,stderr=job.communicate(timeout=120)
            if job.returncode:raise RuntimeError(stderr)
            parallel.append(json.loads(stdout))
        report['parallel_two']={'wall_ms':round((time.perf_counter()-start)*1000,2),'runs':parallel}
        peak=Path('/sys/fs/cgroup/memory.peak')
        if peak.exists():report['container_peak_mib']=round(int(peak.read_text())/1048576,2)
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({**{k:v for k,v in report.items() if k!='cases'},'cases':[{k:v for k,v in c.items() if k!='runs'}|{'status':c['runs'][0]['status'],'counts':c['runs'][0].get('display'),'svg_bytes':max(r.get('svg_bytes',0) for r in c['runs'])} for c in report['cases']]},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
