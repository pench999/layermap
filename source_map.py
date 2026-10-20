"""Typed YAML references and exact AST ranges; never search displayed text."""
import yaml
from typing import Literal
from pydantic import Field
from network_model import Record, Id, ModelError, MAX_YAML_BYTES, BoundedLoader, load_model

Section=Literal['mlag_domains','devices','l1.ports','l1.links','l1.connections','l2.vlans','l2.interfaces','l2.bridges','l3.subnets','l3.interfaces','bindings.l2_to_l1','bindings.l3_to_l2','vpn_connections']
MAX_SOURCE_LOCATIONS=1000
SECTIONS=['mlag_domains','devices','l1.ports','l1.links','l1.connections','l2.vlans','l2.interfaces','l2.bridges','l3.subnets','l3.interfaces','bindings.l2_to_l1','bindings.l3_to_l2','vpn_connections']
class SourceTarget(Record):
    section: Section
    id: Id | None = None
    match: dict[str,Id] = Field(default_factory=dict,max_length=2)
class SourceRequest(Record):
    yaml_text: str = Field(max_length=MAX_YAML_BYTES)
    target: SourceTarget

def child(node,key):
    if isinstance(node,yaml.MappingNode):return next((v for k,v in node.value if k.value==key),None)
    return None

def content_end(node):
    # Block collection end marks can include following comments/indentation.
    if isinstance(node,yaml.ScalarNode) or node.flow_style:return node.end_mark.index
    values=[x for pair in node.value for x in pair] if isinstance(node,yaml.MappingNode) else node.value
    return max((content_end(v) for v in values),default=node.end_mark.index)

def locate_source(request):
    source=request.yaml_text;load_model(source)
    target=request.target
    binding=target.section.startswith('bindings.')
    expected={'l2_interface','physical_port'} if target.section=='bindings.l2_to_l1' else {'l3_interface','l2_interface'}
    if binding:
        if target.id is not None or set(target.match)!=expected:raise ModelError('層間対応は両端のIDで指定してください','target')
    elif target.id is None or target.match:raise ModelError('定義はsectionとidで指定してください','target')
    root=yaml.compose(source,Loader=BoundedLoader)
    records=[];definitions={};selected=None
    for section in SECTIONS:
        node=root
        for key in section.split('.'):node=child(node,key)
        if not isinstance(node,yaml.SequenceNode):continue
        for n,record in enumerate(node.value):
            identity=child(record,'id');key=(section,identity.value) if identity is not None else (section,n)
            entry=dict(key=key,node=record,path=section+f'[{n}]')
            records.append(entry);definitions[key]=entry
            if section==target.section and (identity is not None and identity.value==target.id if not binding else all(child(record,k) is not None and child(record,k).value==v for k,v in target.match.items())):
                if selected is not None:raise ModelError('選択した定義を一意に特定できません','target')
                selected=entry
    if selected is None:raise ModelError('選択した要素の定義が現在のYAMLにありません','target')
    references=[]
    def add(entry,node,section,path):
        if isinstance(node,yaml.ScalarNode) and node.tag=='tag:yaml.org,2002:str':references.append((entry,(section,node.value),node,entry['path']+'.'+path))
    def scalar(entry,field,section):add(entry,child(entry['node'],field),section,field)
    def sequence(entry,field,section):
        node=child(entry['node'],field)
        if isinstance(node,yaml.SequenceNode):
            for j,value in enumerate(node.value):add(entry,value,section,field+f'[{j}]')
    for entry in records:
        section=entry['key'][0];node=entry['node']
        if section in ['l1.ports','l2.interfaces','l2.bridges','l3.interfaces']:scalar(entry,'device','devices')
        if section=='devices':
            sequence(entry,'stack_links','l1.links')
            nodes=child(node,'members')
            if isinstance(nodes,yaml.SequenceNode):
                for j,member in enumerate(nodes.value):add(entry,child(member,'device'),'devices',f'members[{j}].device')
        if section=='mlag_domains':
            sequence(entry,'peers','devices');sequence(entry,'peer_links','l1.links')
            pairs=child(node,'interface_pairs')
            if isinstance(pairs,yaml.SequenceNode):
                for j,pair in enumerate(pairs.value):
                    for k,value in enumerate(pair.value):add(entry,value,'l2.interfaces',f'interface_pairs[{j}][{k}]')
        if section=='l1.links':sequence(entry,'endpoints','l1.ports')
        if section=='l1.connections':
            ends=child(node,'endpoints')
            for j,e in enumerate(ends.value):
                for field,group in [('port','l1.ports'),('device','devices')]:add(entry,child(e,field),group,f'endpoints[{j}].'+field)
        if section=='l2.interfaces':
            add(entry,child(child(node,'aggregation'),'primary_port'),'l1.ports','aggregation.primary_port')
            for field in ['vlan','untagged_vlan']:scalar(entry,field,'l2.vlans')
            sequence(entry,'tagged_vlans','l2.vlans')
        if section=='l2.bridges':sequence(entry,'members','l2.interfaces')
        if section=='l3.interfaces':scalar(entry,'subnet','l3.subnets')
        if section=='bindings.l2_to_l1':
            scalar(entry,'l2_interface','l2.interfaces');scalar(entry,'physical_port','l1.ports')
        if section=='bindings.l3_to_l2':
            scalar(entry,'l3_interface','l3.interfaces');scalar(entry,'l2_interface','l2.interfaces');scalar(entry,'vlan','l2.vlans')
        if section=='vpn_connections':
            for j,e in enumerate(child(node,'endpoints').value):
                add(entry,child(e,'device'),'devices',f'endpoints[{j}].device')
                for k,s in enumerate(child(e,'subnets').value):add(entry,s,'l3.subnets',f'endpoints[{j}].subnets[{k}]')
    # Routes have no ID; include their typed references without inventing IDs.
    routes=child(child(root,'l3'),'routes')
    if isinstance(routes,yaml.SequenceNode):
        for n,node in enumerate(routes.value):
            entry=dict(key=('l3.routes',n),node=node,path=f'l3.routes[{n}]')
            scalar(entry,'device','devices');scalar(entry,'interface','l3.interfaces')
    found={}
    def occurrence(node,path,kind):
        start,end=node.start_mark.index,content_end(node)
        if kind!='definition' and selected['node'].start_mark.index<=start and end<=content_end(selected['node']):return
        key=(start,end)
        if key not in found or kind=='definition':found[key]=dict(start=start,end=end,line=node.start_mark.line+1,column=node.start_mark.column+1,path=path,kind=kind)
    occurrence(selected['node'],selected['path'],'definition')
    for origin,destination,node,p in references:
        if destination==selected['key']:occurrence(node,p,'reference')
        if origin['key']==selected['key'] and destination in definitions:
            related=definitions[destination];occurrence(related['node'],related['path'],'related_definition')
    locations=sorted(found.values(),key=lambda r:(r['kind']!='definition',r['start'],r['end']))
    total=len(locations);locations=locations[:MAX_SOURCE_LOCATIONS]
    offsets={};cursor=units=0
    for pos in sorted({p for r in locations for p in [r['start'],r['end']]}):
        units+=len(source[cursor:pos].encode('utf-16-le'))//2;cursor=pos;offsets[pos]=units
    return dict(locations=[dict(**{k:v for k,v in r.items() if k not in ['start','end']},**{'from':offsets[r['start']],'to':offsets[r['end']]}) for r in locations],total=total,truncated=total>len(locations),limit=MAX_SOURCE_LOCATIONS,
                label=target.section+' / '+(target.id or ' ↔ '.join(target.match.values())))
