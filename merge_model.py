"""Explicit site namespaces, independently validated inputs, no source-file writes."""
import copy
import ipaddress
import json
import re
from collections import defaultdict
import yaml
from pydantic import Field
from network_model import Record,Text,ModelError,load_model,MAX_YAML_BYTES,MAX_DEVICES,MAX_ELEMENTS
from view_model import element_count

MAX_MERGE_FILES=16
MAX_ISSUES=200
MAX_ISSUE_ITEMS=30
SECTIONS=[('devices',),('l1','ports'),('l1','links'),('l1','connections'),('l2','vlans'),('l2','interfaces'),('l2','bridges'),('l3','subnets'),('l3','interfaces')]

class MergeSource(Record):
    site_id: str = Field(min_length=1,max_length=32)
    filename: Text
    yaml_text: str = Field(max_length=MAX_YAML_BYTES)

class MergeRequest(Record):
    sources: list[MergeSource] = Field(min_length=2,max_length=MAX_MERGE_FILES)


def section(model,route):
    return model.get(route[0],[]) if len(route)==1 else model[route[0]].get(route[1],[])


def merge_preview(request):
    if sum(len(s.yaml_text.encode('utf-8')) for s in request.sources)>MAX_YAML_BYTES:
        raise ModelError('統合元YAMLの合計は2 MiB以下にしてください','sources')
    sites=set();inputs=[];devices=elements=0
    for n,source in enumerate(request.sources):
        p=f'sources[{n}]'
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}',source.site_id):
            raise ModelError('拠点IDは英小文字で始まる英小文字・数字・_・-の32文字以内にしてください',p+'.site_id')
        if source.site_id in sites:raise ModelError('拠点IDが重複しています: '+source.site_id,p+'.site_id')
        sites.add(source.site_id)
        try:model=load_model(source.yaml_text)
        except ModelError as error:
            raise ModelError(source.filename+' ['+source.site_id+']: '+str(error),p+'.yaml_text'+('.'+error.path if error.path else ''),error.line,error.column) from None
        devices+=len(model['devices']);elements+=element_count(model)
        if devices>MAX_DEVICES or elements>MAX_ELEMENTS:
            raise ModelError(f'統合後の構成は{MAX_DEVICES}機器・{MAX_ELEMENTS}要素以下にしてください（現在{devices}機器・{elements}要素）','sources')
        inputs.append((source,model))
    merged={'schema':'lan-example/v1','name':'複数拠点の統合構成','scope':'拠点ごとの構成を並列に表示。拠点間接続は未定義。','devices':[],
            'l1':{'ports':[],'links':[],'connections':[]},'l2':{'vlans':[],'interfaces':[],'bridges':[]},
            'l3':{'subnets':[],'interfaces':[],'routes':[]},'bindings':{'l2_to_l1':[],'l3_to_l2':[]},
            'notes':['拠点ID::元IDで識別。元ファイルのコメント・書式は統合元ダウンロードで保持します。','拠点間接続は自動追加しません。同じVLAN番号・IP・サブネットでも拠点ごとの定義を維持します。']}
    mapping=[];summaries=[];header=['# LayerMap 統合結果（元ファイルを変更しない独立した構成）']
    addresses=defaultdict(list);serials=defaultdict(list);names=defaultdict(list);vlan_tags=defaultdict(list);original_ids=defaultdict(list);subnets=[]
    issues=[];issue_count=0;original_note_count=display_note_count=0
    def emit(kind,message,items):
        nonlocal issue_count
        issue_count+=1
        if len(issues)<MAX_ISSUES:issues.append(dict(kind=kind,message=message,items=items[:MAX_ISSUE_ITEMS],total=len(items)))
    for source,original in inputs:
        site=source.site_id
        def rename(value):
            target=site+'::'+value
            if len(target)>100:raise ModelError(source.filename+': 変換後IDが100文字を超えます。拠点IDまたは元IDを短くしてください: '+value,'sources')
            return target
        model=copy.deepcopy(original)
        header.append('# source '+json.dumps({'site_id':site,'filename':source.filename,'name':original.get('name','LAN'),'scope':original.get('scope','社内LAN'),'notes':original.get('notes',[])},ensure_ascii=False))
        changed_sites=sorted({str(d.get('location',{}).get('site','')) for d in original['devices'] if str(d.get('location',{}).get('site',''))!=site})
        for route in SECTIONS:
            kind='.'.join(route)
            for item in section(model,route):
                old=item['id'];item['id']=rename(old)
                mapping.append(dict(site_id=site,section=kind,original=old,converted=item['id']))
                original_ids[(kind,old)].append(site)
                if 'device' in item:item['device']=rename(item['device'])
        for d in model['devices']:
            d.setdefault('location',{})['site']=site
            ref=dict(site_id=site,filename=source.filename,id=d['id'])
            if d.get('serial_number'):serials[d['serial_number']].append(ref)
            if d.get('name'):names[d['name']].append(ref)
        for link in model['l1']['links']:link['endpoints']=[rename(p) for p in link['endpoints']]
        for connection in model['l1'].get('connections',[]):
            for endpoint in connection['endpoints']:
                for key in ['port','device']:
                    if key in endpoint:endpoint[key]=rename(endpoint[key])
        for item in model['l2']['interfaces']:
            for key in ['vlan','untagged_vlan']:
                if item.get(key):item[key]=rename(item[key])
            if 'tagged_vlans' in item:item['tagged_vlans']=[rename(v) for v in item['tagged_vlans']]
        for bridge in model['l2']['bridges']:bridge['members']=[rename(m) for m in bridge['members']]
        for item in model['l3']['interfaces']:
            item['subnet']=rename(item['subnet'])
            addresses[str(ipaddress.ip_interface(item['address']).ip)].append(dict(site_id=site,filename=source.filename,id=item['id'],address=item['address']))
        for item in model['l3']['subnets']:
            subnets.append((ipaddress.ip_network(item['cidr']),dict(site_id=site,filename=source.filename,id=item['id'],cidr=item['cidr'])))
        for item in model['l3'].get('routes',[]):
            for key in ['device','interface']:item[key]=rename(item[key])
        for key,refs in [('l2_to_l1',['l2_interface','physical_port']),('l3_to_l2',['l3_interface','l2_interface','vlan'])]:
            for binding in model['bindings'][key]:
                for ref in refs:binding[ref]=rename(binding[ref])
            merged['bindings'][key].extend(model['bindings'][key])
        for item in model['l2']['vlans']:
            vlan_tags[item['tag']].append(dict(site_id=site,filename=source.filename,id=item['id']))
        for route in SECTIONS:section(merged,route).extend(section(model,route))
        merged['l3']['routes'].extend(model['l3'].get('routes',[]))
        for note in original.get('notes',[]):
            original_note_count+=1;text='['+site+'] '+note
            if len(merged['notes'])<20 and len(text)<=500:merged['notes'].append(text);display_note_count+=1
        summaries.append(dict(site_id=site,filename=source.filename,devices=len(original['devices']),elements=element_count(original),renamed=sum(len(section(original,r)) for r in SECTIONS),previous_sites=changed_sites))
    for kind,groups,label in [('duplicate_ip',addresses,'同じIPアドレス'),('duplicate_serial',serials,'同じシリアルNo'),('duplicate_name',names,'同じ機器名')]:
        for value,items in groups.items():
            if len(items)>1:emit(kind,label+'があります: '+value+'。拠点分離や実機の重複登録を確認してください。',items)
    # Connected overlap groups avoid quadratic pair enumeration for nested networks.
    for version in [4,6]:
        networks=sorted([(int(net.network_address),int(net.broadcast_address),item) for net,item in subnets if net.version==version],key=lambda r:(r[0],r[1]))
        component=[];end=-1
        for start,last,item in networks:
            if component and start>end:
                if len(component)>1:emit('overlapping_subnets','範囲の重なりを含むサブネット群です。拠点間接続時のアドレス設計を確認してください。',component)
                component=[];end=-1
            component.append(item);end=max(end,last)
        if len(component)>1:emit('overlapping_subnets','範囲の重なりを含むサブネット群です。拠点間接続時のアドレス設計を確認してください。',component)
    for tag,items in vlan_tags.items():
        if len({i['site_id'] for i in items})>1:emit('same_vlan_tag',f'VLAN番号{tag}は複数拠点にあります。内部IDを分けて保持し、自動接続しません。',items)
    if original_note_count!=display_note_count:
        emit('notes_display_limit','図に表示する元の注記は先頭18件かつ接頭辞込み500文字以内です。全注記は統合YAMLのsourceコメントと元ファイルに保持します。',[])
    output='\n'.join(header)+'\n'+yaml.safe_dump(merged,allow_unicode=True,sort_keys=False,width=120)
    try:load_model(output)
    except ModelError as error:raise ModelError('統合結果: '+str(error),error.path,error.line,error.column) from None
    return dict(yaml_text=output,sources=summaries,mapping=mapping,issues=issues,issue_count=issue_count,
                issues_truncated=issue_count>len(issues),id_collisions=sum(1 for refs in original_ids.values() if len(refs)>1),
                counts=dict(devices=devices,elements=elements,sites=len(sites)),filename='layermap-merged.yaml')
