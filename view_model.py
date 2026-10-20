from redundancy import stack_members, stack_owners
"""Whole-model validation is separate from a bounded, explicit drawing projection."""
from collections import Counter, defaultdict, deque
from typing import Literal
from pydantic import Field
from network_model import interface_vlans, Record, Id, ModelError, MAX_YAML_BYTES, MAX_DEVICES, MAX_ELEMENTS, all_l1_connections, endpoint_owner, endpoint_label

MAX_VIEW_DEVICES = 24
MAX_VIEW_ROWS = 200
MAX_VIEW_CONNECTIONS = 400
MAX_VIEW_ELEMENTS = 500
MAX_VIEW_GROUPS = 80
MAX_SVG_BYTES = 4 * 1024 * 1024
MAX_HTTP_BYTES = 8 * 1024 * 1024
MAX_RENDER_JOBS = 2


class TraceRoot(Record):
    layer: Literal['l1','l2','l3']
    id: Id


class ViewScope(Record):
    # None means all; empty string means unassigned (valid names are nonempty).
    site: str | None = Field(default=None, max_length=200)
    group: str | None = Field(default=None, max_length=100)
    device_ids: list[Id] = Field(default_factory=list, max_length=MAX_DEVICES)
    trace_root: TraceRoot | None = None
    vpn_id: Id | None = None


def limits():
    return dict(yaml_bytes=MAX_YAML_BYTES, devices=MAX_DEVICES, elements=MAX_ELEMENTS,
                view_devices=MAX_VIEW_DEVICES, view_rows=MAX_VIEW_ROWS,
                view_connections=MAX_VIEW_CONNECTIONS, view_elements=MAX_VIEW_ELEMENTS,
                view_groups=MAX_VIEW_GROUPS, svg_bytes=MAX_SVG_BYTES,
                http_bytes=MAX_HTTP_BYTES, render_jobs=MAX_RENDER_JOBS)


def element_count(model):
    return (len(model['devices'])+sum(len(model[layer][key]) for layer,keys in
            [('l1',['ports','links']),('l2',['vlans','interfaces','bridges']),('l3',['subnets','interfaces'])] for key in keys)
            +len(model.get('mlag_domains',[]))+sum(len(d.get('members',[]))+len(d.get('stack_links',[])) for d in model['devices'])+sum(len(d['peers'])+len(d.get('peer_links',[]))+sum(len(pair) for pair in d.get('interface_pairs',[])) for d in model.get('mlag_domains',[]))+len(model.get('vpn_connections',[]))+len(model['l1'].get('connections',[]))+len(model['l3'].get('routes',[]))+sum(len(v) for v in model['bindings'].values()))


def display_stats(model, layers=None, show_bindings=True):
    wanted=set(layers or ['l1','l2','l3'])
    rows=sum(len(model[layer]['ports' if layer=='l1' else 'interfaces']) for layer in wanted)
    groups=connections=0
    elements=len(model['devices'])+len(model.get('mlag_domains',[]))+sum(len(d.get('members',[]))+len(d.get('stack_links',[])) for d in model['devices'])+sum(len(d['peers'])+len(d.get('peer_links',[]))+sum(len(pair) for pair in d.get('interface_pairs',[])) for d in model.get('mlag_domains',[]))
    if 'l1' in wanted:
        connections+=len(model['l1']['links'])+len(model['l1'].get('connections',[]))
        rows+=sum(sum('port' not in e for e in c['endpoints']) for c in model['l1'].get('connections',[]))
        elements+=len(model['l1']['ports'])+len(model['l1']['links'])+len(model['l1'].get('connections',[]))
    if 'l2' in wanted:
        groups+=len(model['l2']['vlans'])+len(model['l2']['bridges'])
        elements+=len(model['l2']['interfaces'])+len(model['l2']['vlans'])+len(model['l2']['bridges'])
        connections+=sum(len(interface_vlans(i)) for i in model['l2']['interfaces'])
        connections+=sum(len(b['members']) for b in model['l2']['bridges'])
    if 'l3' in wanted:
        vpns=model.get('vpn_connections',[])
        rows+=2*len(vpns);connections+=len(vpns);elements+=3*len(vpns)
        groups+=len(model['l3']['subnets'])
        connections+=len(model['l3']['interfaces'])
        elements+=len(model['l3']['interfaces'])+len(model['l3']['subnets'])+len(model['l3'].get('routes',[]))
    if show_bindings:
        for upper,lower,key in [('l3','l2','l3_to_l2'),('l2','l1','l2_to_l1')]:
            if upper in wanted and lower in wanted:
                connections+=len(model['bindings'][key]);elements+=len(model['bindings'][key])
    return dict(devices=len(model['devices']),rows=rows,connections=connections,
                elements=elements,groups=groups)


def budget_errors(stats):
    caps={'devices':MAX_VIEW_DEVICES,'rows':MAX_VIEW_ROWS,'connections':MAX_VIEW_CONNECTIONS,
          'elements':MAX_VIEW_ELEMENTS,'groups':MAX_VIEW_GROUPS}
    labels={'devices':'機器','rows':'行','connections':'接続・所属','elements':'構成要素','groups':'VLAN・ブリッジ・サブネット'}
    return [f'{labels[k]} {stats[k]}/{cap}' for k,cap in caps.items() if stats[k]>cap]


def require_display_budget(model, layers=None, show_bindings=True):
    problems=budget_errors(display_stats(model,layers,show_bindings))
    if problems:
        raise ModelError('描画上限を超えています（'+', '.join(problems)+'）。拠点・機器群・機器・対応関係で表示を絞り込んでください')


def site_of(device):
    value=device.get('location',{}).get('site')
    return '' if value is None else str(value)


def binding_component(model, root, ix):
    section='l1.ports' if root.layer=='l1' else root.layer+'.interfaces'
    if root.id not in ix[section]:
        raise ModelError('対応関係の起点が見つかりません','scope.trace_root.id')
    adjacency=defaultdict(list)
    for upper,lower,key,ak,bk in [('l3','l2','l3_to_l2','l3_interface','l2_interface'),('l2','l1','l2_to_l1','l2_interface','physical_port')]:
        for binding in model['bindings'][key]:
            a,b=(upper,binding[ak]),(lower,binding[bk])
            adjacency[a].append(b);adjacency[b].append(a)
    start=(root.layer,root.id)
    seen={start};queue=deque([start])
    while queue:
        for node in adjacency[queue.popleft()]:
            if node not in seen:seen.add(node);queue.append(node)
    return seen


def prepare_view(model, ix, scope=None, layers=None, show_bindings=True):
    scope=scope or ViewScope()
    all_devices=list(ix['devices'].values())
    if scope.vpn_id:
        if scope.vpn_id not in ix['vpn_connections']:raise ModelError('VPNが見つかりません','scope.vpn_id')
        vpn=ix['vpn_connections'][scope.vpn_id]
        subnets={s for e in vpn['endpoints'] for s in e['subnets']}
        vpn_owners={e['device'] for e in vpn['endpoints']}|{i['device'] for i in ix['l3.interfaces'].values() if i['subnet'] in subnets}
    else:vpn_owners=None
    chosen=[d for d in all_devices if
            (vpn_owners is None or d['id'] in vpn_owners) and
            (scope.site is None or site_of(d)==scope.site) and
            (scope.group is None or (scope.group in d.get('groups',[]) if scope.group else not d.get('groups'))) and
            (not scope.device_ids or d['id'] in scope.device_ids)]
    # The full catalog stays available even when the current view is too large.
    catalog={'sites':sorted({site_of(d) for d in all_devices}),
             'groups':sorted({g for d in all_devices for g in (d.get('groups') or [''])}),
             'focus_options':[], 'vpns':[dict(id=v['id'],name=v['name']) for v in ix['vpn_connections'].values()]}
    if len(chosen)==1:
        for layer,key in [('l1','l1.ports'),('l2','l2.interfaces'),('l3','l3.interfaces')]:
            for item in ix[key].values():
                if item['device']!=chosen[0]['id']:continue
                value=(item.get('name') or item['id'].split('.')[-1]) if layer=='l1' else item['address'] if layer=='l3' else ('SVI / ' if item['mode']=='svi' else '')+'VLAN '+', '.join(str(ix['l2.vlans'][v]['tag']) for v in interface_vlans(item))
                catalog['focus_options'].append(dict(layer=layer,id=item['id'],label=layer.upper()+' / '+value+' / '+item['id']))
    nodes=binding_component(model,scope.trace_root,ix) if scope.trace_root else None
    scoped=scope.site is not None or scope.group is not None or bool(scope.device_ids) or nodes is not None or scope.vpn_id is not None
    if nodes is not None:
        owners={ix['l1.ports' if layer=='l1' else layer+'.interfaces'][identity]['device'] for layer,identity in nodes}
        chosen=[d for d in chosen if d['id'] in owners]
    # A logical stack and its physical chassis are one explicit display unit.
    expanded={d['id'] for d in chosen};stack_context=[]
    for d in all_devices:
        if d.get('kind')!='stack':continue
        unit={d['id']}|stack_members(d['id'],ix)
        if unit&expanded:
            if not unit<=expanded:stack_context.append(d['id'])
            expanded.update(unit)
    chosen=[d for d in all_devices if d['id'] in expanded]
    owners=expanded
    def items(layer,key):
        return [dict(i) for i in ix[layer+'.'+key].values() if i['device'] in owners and (nodes is None or (layer,i['id']) in nodes)]
    ports=items('l1','ports');l2=items('l2','interfaces');l3=items('l3','interfaces')
    port_ids={i['id'] for i in ports};l2_ids={i['id'] for i in l2};l3_ids={i['id'] for i in l3}
    links=[dict(l) for l in ix['l1.links'].values() if all(p in port_ids for p in l['endpoints'])]
    extra=[]
    boundary=[]
    for connection in all_l1_connections(ix):
        def visible(e):
            return e['port'] in port_ids if 'port' in e else e['device'] in owners and nodes is None if 'device' in e else False
        seen=[visible(e) for e in connection['endpoints']]
        # An explicitly unknown peer is part of the visible observation, never a hidden known device.
        unknown=any('unknown' in e for e in connection['endpoints'])
        if all(seen) or (unknown and any(seen)):
            if connection['id'] in ix['l1.connections']:extra.append(dict(connection))
        elif any(seen):
            local,remote=(connection['endpoints'][seen.index(True)],connection['endpoints'][seen.index(False)])
            boundary.append(dict(id=connection['id'],local=endpoint_label(local),remote=endpoint_label(remote),remote_device=endpoint_owner(remote,ix),kind=connection['kind'],status=connection['status'],ssid=connection.get('ssid'),observed_at=connection.get('observed_at')))
    vlan_ids={v for i in l2 for v in interface_vlans(i)}
    subnet_ids={i['subnet'] for i in l3}
    bridges=[]
    for bridge in ix['l2.bridges'].values():
        if bridge['device'] in owners:
            members=[m for m in bridge['members'] if m in l2_ids]
            if members or not scoped:bridges.append(dict(bridge,members=members))
    notes=[]
    if stack_context:notes.append('STACKの物理メンバーと論理機器を表示範囲に含めています: '+', '.join(stack_context))
    if scoped:
        notes.insert(0,'表示範囲を絞り込んでいます。構成全体のYAMLは保持されています。')
        if boundary:notes.insert(1,f'範囲外に接続する{"L1接続" if ix["l1.connections"] else "ケーブル"}{len(boundary)}本は図から省略しています。接続先は画面の範囲外接続一覧で確認してください。')
    projected={'schema':model['schema'],'name':model.get('name','LAN'),'scope':model.get('scope','社内LAN'),
       'devices':chosen,'l1':{'ports':ports,'links':links,'connections':extra},
       'l2':{'interfaces':l2,'vlans':[dict(v) for v in ix['l2.vlans'].values() if not scoped or v['id'] in vlan_ids],'bridges':bridges},
       'l3':{'interfaces':l3,'subnets':[dict(s) for s in ix['l3.subnets'].values() if not scoped or s['id'] in subnet_ids],
             'routes':[r for r in model['l3'].get('routes',[]) if r['interface'] in l3_ids]},
       'bindings':{'l2_to_l1':[b for b in model['bindings']['l2_to_l1'] if b['l2_interface'] in l2_ids and b['physical_port'] in port_ids],
                   'l3_to_l2':[b for b in model['bindings']['l3_to_l2'] if b['l3_interface'] in l3_ids and b['l2_interface'] in l2_ids]},
       'notes':list(model.get('notes',[]))}
    link_ids={l['id'] for l in links}
    projected['devices']=[dict(d,stack_links=[lid for lid in d.get('stack_links',[]) if lid in link_ids]) for d in chosen]
    projected['mlag_domains']=[]
    for domain in ix['mlag_domains'].values():
        if set(domain['peers'])<=owners:
            projected['mlag_domains'].append(dict(domain,peer_links=[lid for lid in domain['peer_links'] if lid in link_ids],interface_pairs=[pair for pair in domain['interface_pairs'] if set(pair)<=l2_ids]))
        elif set(domain['peers'])&owners:notes.append('範囲外のpeerがあるためMLAGドメイン '+domain['id']+' の関係表示を省略しています。各機器は独立して表示します。')
    visible_vpns=[];hidden_vpns=[]
    for vpn in ix['vpn_connections'].values():
        if scope.vpn_id and vpn['id']!=scope.vpn_id:continue
        if all(e['device'] in owners and all(s in subnet_ids for s in e['subnets']) for e in vpn['endpoints']):visible_vpns.append(vpn)
        elif any(e['device'] in owners or any(s in subnet_ids for s in e['subnets']) for e in vpn['endpoints']):hidden_vpns.append(vpn['id'])
    if visible_vpns:projected['vpn_connections']=visible_vpns
    if hidden_vpns:notes.append('範囲外のVPN終端・対象サブネットがあるためVPN '+', '.join(hidden_vpns)+'を省略しています。VPNの表示範囲を選択すると両端を確認できます。')
    stats=display_stats(projected,layers,show_bindings)
    problems=budget_errors(stats)
    status='empty' if not chosen else 'too_large' if problems else 'ready'
    message=('該当する機器・対応関係がありません。表示条件を変更してください。' if status=='empty' else
             '描画上限を超えています（'+', '.join(problems)+'）。拠点・機器群・機器・対応関係で絞り込んでください。' if problems else '')
    metadata={'status':status,'counts':stats,'message':message,'filtered':scoped,
              'context_notes':notes,'boundary_links':{'noun':'L1接続' if ix['l1.connections'] else 'ケーブル','total':len(boundary),'items':boundary[:100],'has_more':len(boundary)>100}}
    return projected,metadata,catalog
