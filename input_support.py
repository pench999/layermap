"""Stateless, validated additive edits. Existing YAML characters are never re-emitted."""
import difflib
import json
from typing import Literal, Annotated
import yaml
from pydantic import Field
from network_model import (Record, Device, Id, Text, Connection, ModelError, load_model,
                           BoundedLoader, BaseLoader, all_l1_connections)


class DeviceOperation(Record):
    type: Literal['device']
    device: Device
    port_kind: Literal['wired','wifi'] = 'wired'
    port_count: int = Field(default=1,ge=1,le=24)
    port_prefix: Text = 'Gi1/0/'
    port_start: int = Field(default=1,ge=1,le=9999)
    configure_l2: bool = True
    mode: Literal['access','trunk'] = 'access'
    vlans: list[Id] = Field(default_factory=list,max_length=64)
    address: Text | None = None
    subnet: Id | None = None
    ip_vlan: Id | None = None
    gateway: Text | None = None


class ConnectionOperation(Record):
    type: Literal['connection']
    connection: Connection


Operation = Annotated[DeviceOperation | ConnectionOperation, Field(discriminator='type')]


def catalog(source):
    model,ix=load_model(source,with_index=True)
    occupied={e['port'] for c in all_l1_connections(ix) if c['kind']=='wired' for e in c['endpoints'] if 'port' in e}
    return {'devices':[{'id':d['id'],'name':d.get('name') or d['id'],'role':d['role']} for d in ix['devices'].values()],
            'ports':[dict(p,occupied=p['id'] in occupied) for p in ix['l1.ports'].values()],
            'vlans':list(ix['l2.vlans'].values()),'subnets':list(ix['l3.subnets'].values())}


def device_additions(op,ix):
    d=op.device.model_dump(exclude_none=True)
    if d['id'] in ix['devices']:raise ModelError('この機器IDは既に使われています','device.id')
    role=d['role'];identity=d['id']
    if role not in ['endpoint','l2-switch','access-point','internet-gateway']:
        raise ModelError('ウィザードではPC・スイッチ・AP・ゲートウェイを選んでください','device.role')
    if role=='endpoint':specs=[('wlan0' if op.port_kind=='wifi' else 'eth0','Wi-Fi' if op.port_kind=='wifi' else 'Ethernet0',op.port_kind)]
    elif role=='access-point':specs=[('eth0','LAN1','wired'),('wlan0','Radio0','wifi')]
    else:specs=[('p'+str(n) if role=='l2-switch' else 'lan'+str(n),op.port_prefix+str(n),'wired') for n in range(op.port_start,op.port_start+op.port_count)]
    ports=[dict(id=identity+'.'+suffix,device=identity,name=name,kind=kind) for suffix,name,kind in specs]
    result={('devices',):[d],('l1','ports'):ports}
    if not op.configure_l2:
        if op.address or op.subnet or op.gateway:raise ModelError('IP設定にはL2設定が必要です','address')
        return result
    if role=='endpoint' and op.port_kind=='wifi' and (op.mode!='access' or len(op.vlans)!=1):
        raise ModelError('Wi-Fi端末はaccessでVLANを一つ選んでください','mode')
    if not op.vlans:raise ModelError('使用するVLANを選んでください','vlans')
    if len(set(op.vlans))!=len(op.vlans):raise ModelError('VLANが重複しています','vlans')
    if op.mode=='access' and len(op.vlans)!=1:raise ModelError('accessはVLANを一つ選んでください','vlans')
    for v in op.vlans:
        if v not in ix['l2.vlans']:raise ModelError('選択したVLANが見つかりません','vlans')
    interfaces=[]
    for p in ports:
        # AP radio is access on the explicitly selected first VLAN; uplink may be trunk.
        mode='access' if p['kind']=='wifi' else op.mode
        item=dict(id=p['id']+'.l2',device=identity,mode=mode)
        item.update({'untagged_vlan':op.vlans[0]} if mode=='access' else {'tagged_vlans':op.vlans})
        interfaces.append(item)
    result[('l2','interfaces')]=interfaces
    result[('bindings','l2_to_l1')]=[dict(l2_interface=i['id'],physical_port=p['id']) for i,p in zip(interfaces,ports)]
    if role in ['l2-switch','access-point']:
        result[('l2','bridges')]=[dict(id=identity+'.bridge',device=identity,members=[i['id'] for i in interfaces])]
    if op.address:
        if not op.subnet:raise ModelError('IPの所属サブネットを選んでください','subnet')
        if op.ip_vlan not in op.vlans:raise ModelError('IPに対応するVLANを選んでください','ip_vlan')
        if interfaces[0]['mode']=='access' and op.ip_vlan!=op.vlans[0]:raise ModelError('先頭IFのVLANとIPのVLANを一致させてください','ip_vlan')
        result[('l3','interfaces')]=[dict(id=identity+'.ip',device=identity,address=op.address,subnet=op.subnet)]
        result[('bindings','l3_to_l2')]=[dict(l3_interface=identity+'.ip',l2_interface=interfaces[0]['id'],vlan=op.ip_vlan)]
        if op.gateway:result[('l3','routes')]=[dict(device=identity,destination='::/0' if ':' in op.address else '0.0.0.0/0',next_hop=op.gateway,interface=identity+'.ip')]
    elif op.subnet or op.gateway:raise ModelError('IPアドレスを入力してください','address')
    return result


def append_records(source,additions):
    """Insert at token boundaries, leaving comments, quotes, indentation and tails intact."""
    root=yaml.compose(source,Loader=BoundedLoader)
    tokens=list(yaml.scan(source,Loader=BaseLoader))
    eol='\r\n' if '\r\n' in source else '\r' if '\r' in source and '\n' not in source else '\n'
    significant=(yaml.ScalarToken,yaml.FlowSequenceEndToken,yaml.FlowMappingEndToken)
    edits=[]
    def after_content(node):
        ends=[t.end_mark.index for t in tokens if isinstance(t,significant) and t.start_mark.index>=node.start_mark.index and t.end_mark.index<=node.end_mark.index]
        pos=max(ends,default=node.start_mark.index)
        if pos and source[pos-1] in '\r\n':return pos
        end=pos
        while end<len(source) and source[end] not in '\r\n':end+=1
        if end<len(source):end+=2 if source[end:end+2]=='\r\n' else 1
        return end
    def flow_insert(node,value,has_items,last_end):
        close=node.end_mark.index-1
        trailing=any(isinstance(t,yaml.FlowEntryToken) and t.start_mark.index>=last_end and t.end_mark.index<=close for t in tokens)
        prefix=',' if has_items and not trailing else ''
        line_start=max(source.rfind('\n',0,node.start_mark.index),source.rfind('\r',0,node.start_mark.index))+1
        line=source[line_start:node.start_mark.index]
        indent=len(line)-len(line.lstrip(' '))
        return close,prefix+eol+' '*(indent+2)+value.replace(eol,eol+' '*(indent+2))+eol+' '*(indent+2)
    for route,records in additions.items():
        parent=root
        for key in route[:-1]:
            parent=next(v for k,v in parent.value if k.value==key)
        key=route[-1]
        target=next((v for k,v in parent.value if k.value==key),None)
        encoded=[json.dumps(r,ensure_ascii=False,separators=(', ',': ')) for r in records]
        if target is not None:
            if not isinstance(target,yaml.SequenceNode):raise ModelError('追加先はリストである必要があります','.'.join(route))
            if target.flow_style:
                pos,value=flow_insert(target,(', '+eol).join(encoded),bool(target.value),target.value[-1].end_mark.index if target.value else target.start_mark.index+1)
            else:
                pos=after_content(target)
                value=('' if pos and source[pos-1] in '\r\n' else eol)+''.join(' '*target.start_mark.column+'- '+r+eol for r in encoded)
        elif parent.flow_style:
            value=json.dumps(key)+': ['+', '.join(encoded)+']'
            pos,value=flow_insert(parent,value,bool(parent.value),parent.value[-1][1].end_mark.index if parent.value else parent.start_mark.index+1)
        else:
            pos=after_content(parent);indent=parent.start_mark.column
            value=('' if pos and source[pos-1] in '\r\n' else eol)+' '*indent+key+':'+eol+''.join(' '*(indent+2)+'- '+r+eol for r in encoded)
        edits.append({'from':pos,'to':pos,'insert':value,'path':'.'.join(route)})
    # Several absent keys can have the same insertion point in one mapping.
    merged={}
    for edit in edits:
        pos=edit['from']
        if pos in merged:merged[pos]['insert']+=edit['insert'];merged[pos]['path']+=', '+edit['path']
        else:merged[pos]=dict(edit)
    changes=sorted(merged.values(),key=lambda e:e['from'])
    candidate=source
    for edit in reversed(changes):candidate=candidate[:edit['from']]+edit['insert']+candidate[edit['to']:]
    return candidate,[dict(e,**{'from':len(source[:e['from']].encode('utf-16-le'))//2,'to':len(source[:e['to']].encode('utf-16-le'))//2}) for e in changes]


def preview(source,operation):
    model,ix=load_model(source,with_index=True)
    additions=device_additions(operation,ix) if isinstance(operation,DeviceOperation) else {('l1','connections'):[operation.connection.model_dump(exclude_none=True)]}
    candidate,changes=append_records(source,additions)
    load_model(candidate)  # Validate complete references, occupancy and all capacity limits.
    return {'yaml_text':candidate,'changes':changes,
            'summary':[{'path':'.'.join(k),'count':len(v)} for k,v in additions.items()],
            'diff':''.join(difflib.unified_diff(source.splitlines(keepends=True),candidate.splitlines(keepends=True),fromfile='現在のYAML',tofile='適用後のYAML',n=3))}
