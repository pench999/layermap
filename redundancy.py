"""Explicit physical chassis, logical stacks and independent MLAG peers."""
from collections import defaultdict
from network_model import ModelError, interface_vlans


def stack_members(identity, ix):
    device=ix['devices'][identity]
    return {m['device'] for m in device.get('members',[])} if device.get('kind')=='stack' else {identity}


def stack_owners(ix):
    return {m['device']:d['id'] for d in ix['devices'].values() if d.get('kind')=='stack' for m in d.get('members',[])}


def layer_devices(ix,layer):
    members=stack_owners(ix)
    return [d for d in ix['devices'] if (ix['devices'][d].get('kind')!='stack' if layer=='l1' else d not in members)]


def validate_equipment(data,ix):
    used=set()
    for n,d in enumerate(data['devices']):
        p=f'devices[{n}]'
        if d['kind']=='physical':
            if d['members'] or d['stack_links']:raise ModelError('members・stack_linksはkind: stack専用です',p)
            continue
        if len(d['members'])<2:raise ModelError('STACKには2台以上の物理機器を指定してください',p+'.members')
        if d.get('serial_number'):raise ModelError('シリアルNoはSTACKの各物理機器に記述してください',p+'.serial_number')
        numbers=set()
        for j,m in enumerate(d['members']):
            q=p+f'.members[{j}]';peer=ix['devices'].get(m['device'])
            if peer is None or peer['kind']!='physical':raise ModelError('STACKのメンバーには実在する物理機器を指定してください',q+'.device')
            if m['device'] in used or m['number'] in numbers:raise ModelError('STACKの所属機器またはメンバー番号が重複しています',q)
            if str(peer.get('location',{}).get('site',''))!=str(d.get('location',{}).get('site','')):raise ModelError('STACKとメンバーの拠点を揃えてください',q+'.device')
            used.add(m['device']);numbers.add(m['number'])
    owners=stack_owners(ix)
    for group in ['l1.ports','l2.interfaces','l2.bridges','l3.interfaces']:
        for n,item in enumerate(ix[group].values()):
            device=ix['devices'].get(item['device'])
            if device is None:continue
            if group=='l1.ports' and device['kind']=='stack':raise ModelError('物理ポートはSTACKの物理メンバーへ所属させてください',group+f'[{n}].device')
            if group!='l1.ports' and item['device'] in owners:raise ModelError('STACKのL2・L3定義は論理STACK機器へ所属させてください',group+f'[{n}].device')
    for n,c in enumerate(ix['l1.connections'].values()):
        for e in c['endpoints']:
            if e.get('device') in ix['devices'] and ix['devices'][e['device']]['kind']=='stack':raise ModelError('L1の接続先はSTACKの物理機器を指定してください',f'l1.connections[{n}].endpoints')


def validate_aggregations(data,ix):
    members=defaultdict(list);port_ifs=defaultdict(set)
    for n,b in enumerate(data['bindings']['l2_to_l1']):
        members[b['l2_interface']].append(b['physical_port']);port_ifs[b['physical_port']].add(b['l2_interface'])
    aggregate_ports=set()
    for n,i in enumerate(data['l2']['interfaces']):
        a=i.get('aggregation');p=f'l2.interfaces[{n}].aggregation'
        if not a:continue
        ports=members[i['id']]
        if i['mode']=='svi' or not ports or len(set(ports))!=len(ports):raise ModelError('集約IFには異なる物理ポート1本以上の対応が必要です。SVIには指定できません',p)
        if a['kind']=='lag' and a['mode']=='active_backup':raise ModelError('active_backupはbondまたはteamで指定してください',p+'.mode')
        if a.get('primary_port') and (a['mode']!='active_backup' or a['primary_port'] not in ports):raise ModelError('primary_portはactive_backupのメンバーポートから選んでください',p+'.primary_port')
        for port in ports:
            if ix['l1.ports'][port]['kind']!='wired' or len(port_ifs[port])!=1:raise ModelError('集約メンバーには専用の有線ポートを指定してください',p)
        aggregate_ports.update(ports)
    def unique(values,p):
        if len(values)!=len(set(values)):raise ModelError('参照が重複しています',p)
    reserved=set()
    for n,d in enumerate(data['devices']):
        if d['kind']!='stack':continue
        unique(d['stack_links'],f'devices[{n}].stack_links')
        physical=stack_members(d['id'],ix)
        for link_id in d['stack_links']:
            link=ix['l1.links'].get(link_id)
            if link is None or len({ix['l1.ports'][p]['device'] for p in link['endpoints']})!=2 or any(ix['l1.ports'][p]['device'] not in physical for p in link['endpoints']):raise ModelError('stack_linksには異なる所属筐体間のL1ケーブルを指定してください',f'devices[{n}].stack_links')
            reserved.update(link['endpoints'])
    for port in reserved:
        if port in port_ifs:raise ModelError('STACK専用ポートは通常のL2インターフェースへ対応付けられません','bindings.l2_to_l1')
    paired=set();peer_domains=set();peer_link_ids=set()
    for n,d in enumerate(data['mlag_domains']):
        p=f'mlag_domains[{n}]';unique(d['peers'],p+'.peers');unique(d['peer_links'],p+'.peer_links')
        if any(peer not in ix['devices'] for peer in d['peers']):raise ModelError('MLAGのpeer機器が見つかりません',p+'.peers')
        physical=[stack_members(peer,ix) for peer in d['peers']]
        if physical[0]&physical[1] or any(peer in stack_owners(ix) for peer in d['peers']):raise ModelError('MLAGは独立した物理機器または論理STACK同士で定義してください',p+'.peers')
        if any(peer in peer_domains for peer in d['peers']):raise ModelError('同じ機器を複数のMLAGドメインへ所属させられません',p+'.peers')
        peer_domains.update(d['peers'])
        sites={str(ix['devices'][peer].get('location',{}).get('site','')) for peer in d['peers']}
        if len(sites)!=1:raise ModelError('MLAGのpeerは同じ拠点にしてください',p+'.peers')
        for lid in d['peer_links']:
            link=ix['l1.links'].get(lid)
            if link is None:raise ModelError('MLAG peer-linkのL1ケーブルが見つかりません',p+'.peer_links')
            ends=[ix['l1.ports'][v]['device'] for v in link['endpoints']]
            if not ((ends[0] in physical[0] and ends[1] in physical[1]) or (ends[1] in physical[0] and ends[0] in physical[1])):raise ModelError('peer_linksには両peer間の物理ケーブルを指定してください',p+'.peer_links')
            if lid in peer_link_ids or any(v in reserved for v in link['endpoints']):raise ModelError('peer-linkとSTACK接続の所属が重複しています',p+'.peer_links')
            peer_link_ids.add(lid)
        for j,pair in enumerate(d['interface_pairs']):
            q=p+f'.interface_pairs[{j}]';unique(pair,q)
            interfaces=[ix['l2.interfaces'].get(v) for v in pair]
            if any(i is None or not i.get('aggregation') or i['aggregation']['kind']!='lag' for i in interfaces):raise ModelError('MLAGペアには両peerのLAGインターフェースを指定してください',q)
            if {i['device'] for i in interfaces}!=set(d['peers']):raise ModelError('MLAGペアのLAGを各peerへ一つずつ所属させてください',q)
            if any(v in paired for v in pair):raise ModelError('同じLAGを複数のMLAGペアに指定できません',q)
            if len({(i['mode'],tuple(sorted(interface_vlans(i))),i['aggregation']['mode']) for i in interfaces})!=1:raise ModelError('MLAGペアのVLAN・L2モード・集約方式を揃えてください',q)
            paired.update(pair)
    # Only compare peer settings when every physical end and L2 mapping is known.
    # Partial diagrams and unconfirmed connections must not invent peer identity.
    remote={}
    for link in ix['l1.links'].values():
        a,b=link['endpoints'];remote[a]=b;remote[b]=a
    for c in ix['l1.connections'].values():
        if c['kind']=='wired' and c['status']=='confirmed':
            a,b=[e['port'] for e in c['endpoints']];remote[a]=b;remote[b]=a
    mlag_pairs={frozenset(pair) for d in ix['mlag_domains'].values() for pair in d['interface_pairs']}
    for n,i in enumerate(data['l2']['interfaces']):
        agg=i.get('aggregation')
        if not agg or agg['mode']=='active_backup':continue
        ports=members[i['id']]
        if not all(p in remote and remote[p] in port_ifs and len(port_ifs[remote[p]])==1 for p in ports):continue
        targets={next(iter(port_ifs[remote[p]])) for p in ports}
        if any(not ix['l2.interfaces'][t].get('aggregation') or ix['l2.interfaces'][t]['aggregation']['mode']!=agg['mode'] for t in targets):raise ModelError('確認済み接続の対向集約IFとLACP/static方式が一致しません',f'l2.interfaces[{n}].aggregation')
        if len(targets)>1 and frozenset(targets) not in mlag_pairs:raise ModelError('複数の対向LAGへ接続する場合はMLAGのinterface_pairsを定義してください',f'l2.interfaces[{n}].aggregation')
