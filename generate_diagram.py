"""Render the shared network model as one equipment card per device per layer."""
import argparse
import html
import json
from vpn_model import vpn_members
from redundancy import stack_owners, layer_devices
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

import yaml
from network_model import interface_vlans, ModelError, validate, load_model, endpoint_owner, endpoint_label, connection_label
from view_model import require_display_budget, prepare_view, ViewScope, TraceRoot


def wrap_label(value, columns=44):
    """Wrap by approximate glyph width, including Japanese and unbroken IDs."""
    lines, current, used = [], '', 0
    for character in str(value):
        size = 2 if unicodedata.east_asian_width(character) in ('W', 'F') else 1
        if character == '\n' or used + size > columns:
            lines.append(current)
            current, used = '', 0
            if character == '\n':
                continue
        current += character
        used += size
    if current or not lines:
        lines.append(current)
    return lines


def compact_path(points):
    result=[]
    for point in points:
        if result and point==result[-1]:
            continue
        result.append(point)
        while len(result)>2 and ((result[-3][0]==result[-2][0]==result[-1][0]) or (result[-3][1]==result[-2][1]==result[-1][1])):
            result.pop(-2)
    return result


def segments(points):
    return list(zip(points,points[1:]))


def segment_conflict(first,second):
    """Return (positive-length overlap, crossing/touch); never create junctions."""
    (a,b),(c,d)=first,second
    horizontal=a[1]==b[1]
    other_horizontal=c[1]==d[1]
    if horizontal==other_horizontal:
        axis=0 if horizontal else 1
        fixed=1-axis
        if a[fixed]!=c[fixed]:
            return (0,0)
        overlap=min(max(a[axis],b[axis]),max(c[axis],d[axis]))-max(min(a[axis],b[axis]),min(c[axis],d[axis]))
        return (1,0) if overlap>0 else (0,int(overlap==0))
    if not horizontal:
        a,b,c,d=c,d,a,b
    cross=min(a[0],b[0])<=c[0]<=max(a[0],b[0]) and min(c[1],d[1])<=a[1]<=max(c[1],d[1])
    return (0,int(cross))


def hits_card(points,boxes):
    for a,b in segments(points):
        for left,top,right,bottom in boxes:
            if a[1]==b[1] and top<a[1]<bottom and max(min(a[0],b[0]),left)<min(max(a[0],b[0]),right):
                return True
            if a[0]==b[0] and left<a[0]<right and max(min(a[1],b[1]),top)<min(max(a[1],b[1]),bottom):
                return True
    return False


def route_cables(links,nodes,boxes,card_top,bottom):
    """Greedy orthogonal routing: avoid equipment, then shared segments and crossings.

    Adjacent-device cables are placed first. Remaining cables can use independent
    upper/lower tracks. Endpoints are always the actual port coordinates.
    """
    palette=['#1779a5','#b5681c','#287c58','#a04a92','#6a64b0','#ad574d']
    prior=[]
    routes={}
    order=sorted(range(len(links)),key=lambda i:(abs(nodes[links[i]['endpoints'][0]]['left']-nodes[links[i]['endpoints'][1]]['left']),i))
    for track,i in enumerate(order):
        link=links[i]
        a,b=[nodes[p] for p in link['endpoints']]
        pa,pb=(a['anchor_x'],a['y']),(b['anchor_x'],b['y'])
        candidates=[]
        if a['device']!=b['device']:
            lo,hi=sorted([pa[0],pb[0]])
            for fraction in [.5,.25,.75,.125,.875]:
                mid=lo+(hi-lo)*fraction
                candidates.append([pa,(mid,pa[1]),(mid,pb[1]),pb])
        for extra in [0,9,18]:
            ea=pa[0]+a['side']*(18+7*a['slot']+extra)
            eb=pb[0]+b['side']*(18+7*b['slot']+extra)
            for lane_y in [card_top-24-track*20,bottom+36+track*24]:
                candidates.append([pa,(ea,pa[1]),(ea,lane_y),(eb,lane_y),(eb,pb[1]),pb])
        choices=[]
        for raw in candidates:
            points=compact_path(raw)
            if hits_card(points,boxes) or min(p[0] for p in points)<8:
                continue
            overlap=cross=0
            for segment in segments(points):
                for existing in prior:
                    o,c=segment_conflict(segment,existing)
                    overlap+=o
                    cross+=c
            length=sum(abs(b[0]-a[0])+abs(b[1]-a[1]) for a,b in segments(points))
            choices.append(((overlap,cross,length,len(points)),points))
        if not choices:
            raise ModelError('L1のケーブル経路を確保できませんでした')
        _,points=min(choices,key=lambda item:item[0])
        prior.extend(segments(points))
        routes[link['id']]={'points':points,'color':palette[i%len(palette)],'number':f'C{i+1}'}
    return routes


def ghost_height(connection):
    return 20+16*(1+len(wrap_label(connection['id'],44)))


def wave_path(points):
    # One continuous path, with bounded detail even for very long routed segments.
    import math
    parts=[f'M{points[0][0]},{points[0][1]}']
    for a,b in segments(points):
        dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
        steps=max(1,min(128,int(length/12)))
        for n in range(steps):
            t=(n+1)/steps;mid=(n+.5)/steps;sign=1 if n%2==0 else -1
            cx=a[0]+dx*mid-dy/length*3*sign;cy=a[1]+dy*mid+dx/length*3*sign
            parts.append(f'Q{cx:.2f},{cy:.2f} {a[0]+dx*t:.2f},{a[1]+dy*t:.2f}')
    return ' '.join(parts)


def render(model, layers=None, show_bindings=True, context_notes=None):
    ix = validate(model)
    wanted = tuple(layers) if layers is not None else ('l3', 'l2', 'l1')
    if not wanted or len(set(wanted)) != len(wanted) or any(l not in ('l1','l2','l3') for l in wanted):
        raise ModelError('表示するレイヤーはl1・l2・l3から選択してください')
    require_display_budget(model, wanted, show_bindings)
    devices = list(ix['devices'])
    chassis_stacks=stack_owners(ix)
    stack_link_ids={lid for d in ix['devices'].values() for lid in d.get('stack_links',[])}
    mlag_link_ids={lid for domain in ix['mlag_domains'].values() for lid in domain['peer_links']}
    domain_labels={peer:[] for peer in devices}
    for domain in ix['mlag_domains'].values():
        for peer in domain['peers']:domain_labels[peer].append('MLAG / '+domain['name']+' / 独立管理')
    specs = [('l3','l3.interfaces','L3 / IPインターフェース・サブネット','#eaf3fc'),
             ('l2','l2.interfaces','L2 / VLAN・ブリッジ','#edf6ef'),
             ('l1','l1.ports','L1 / 物理ポート・ケーブル','#f0eff7')]
    specs = [spec for spec in specs if spec[0] in wanted]
    palette = ['#1676b5','#b56316','#18856c','#af3982','#5e56ba']
    colors = {v:palette[n%len(palette)] for n,v in enumerate(ix['l2.vlans'])}
    relations = {}
    for layer, group, _, _ in specs:
        items = list(ix[group].values())
        if layer == 'l3':
            relations[layer] = [(s['id']+' / '+s['cidr'],[i['id'] for i in items if i['subnet']==s['id']],palette[n%len(palette)]) for n,s in enumerate(ix['l3.subnets'].values())]
        elif layer == 'l2':
            relations[layer] = [(v['id']+' / VLAN '+str(v['tag'])+' / '+v.get('label',''),
                                 [i['id'] for i in items if v['id'] in interface_vlans(i)],colors[v['id']]) for v in ix['l2.vlans'].values()]
            relations[layer] += [(b['id']+(' / VLAN内の転送・SVI終端' if any(ix['l2.interfaces'][m]['mode']=='svi' for m in b['members']) else ' / VLAN別に転送'),b['members'],'#48794b') for b in ix['l2.bridges'].values()]
        else:
            relations[layer] = []  # Physical cables are independent point-to-point paths.
    # Memberships are explicit: VLAN/subnet badges get distinct connection points.
    networks = {}
    memberships = {}
    for layer, group, _, _ in specs:
        ids = (list(ix['l3.subnets']) if layer=='l3' else
               list(ix['l2.vlans'])+list(ix['l2.bridges']) if layer=='l2' else [])
        networks[layer] = []
        for n,((label,members,color),identity) in enumerate(zip(relations[layer],ids)):
            kind = 'subnet' if layer=='l3' else 'vlan' if n<len(ix['l2.vlans']) else 'bridge'
            ordinal = n+1 if kind!='bridge' else n-len(ix['l2.vlans'])+1
            number = {'subnet':'S','vlan':'V','bridge':'B'}[kind]+str(ordinal)
            network = {'key':f'{layer}-{n}', 'id':identity, 'number':number,
                       'kind':kind, 'label':label, 'members':members, 'color':color}
            networks[layer].append(network)
            for member in members:
                memberships.setdefault((layer,member),[]).append(network)
    physical_links=list(ix['l1.links'].values())
    extra_connections=list(ix['l1.connections'].values())
    ghosts={device:[] for device in ix['devices']}
    for index,c in enumerate(extra_connections):
        for j,e in enumerate(c['endpoints']):
            if 'device' in e:ghosts[e['device']].append((index,j,c))
    physical_degree=Counter(ix['l1.ports'][p]['device'] for link in physical_links for p in link['endpoints'])
    physical_degree.update(endpoint_owner(e,ix) for c in extra_connections for e in c['endpoints'] if endpoint_owner(e,ix) is not None)
    max_edges = max([max(Counter(ix[group][m]['device'] for _,members,_ in relations[layer] for m in members).values(),default=0) for layer,group,_,_ in specs]+[max(physical_degree.values(),default=1) if 'l1' in wanted else 1])
    binding_specs = [('l3','l2','l3_to_l2','l3_interface','l2_interface'),('l2','l1','l2_to_l1','l2_interface','physical_port')]
    binding_records, row_bindings = [], {}
    if show_bindings:
        for upper,lower,kind,ak,bk in binding_specs:
            if upper not in wanted or lower not in wanted:
                continue
            for original in model['bindings'][kind]:
                number='M'+str(len(binding_records)+1)
                record={'key':'map-'+str(len(binding_records)), 'number':number,
                        'upper':upper, 'lower':lower, 'kind':kind,
                        'source':original[ak], 'target':original[bk],
                        'vlan':original.get('vlan'), 'device':ix[upper+'.interfaces'][original[ak]]['device']}
                record['label']=number+' / '+upper.upper()+': '+record['source']+' ↔ '+lower.upper()+': '+record['target']+(' / VLAN '+record['vlan'] if record['vlan'] else '')
                binding_records.append(record)
                row_bindings.setdefault((upper,record['source']),[]).append(record)
                row_bindings.setdefault((lower,record['target']),[]).append(record)
    def binding_badge(record,layer):
        upper=layer==record['upper']
        other=record['lower'] if upper else record['upper']
        target=record['target'] if upper else record['source']
        return record['number']+(' ↓ ' if upper else ' ↑ ')+other.upper()+' / '+target+(' / '+record['vlan'] if record['vlan'] else '')
    max_bindings = max(Counter(b['device'] for b in binding_records).values(),default=0)
    card_width = 340
    left_space = max(60, 34 + max_bindings*20)
    column = card_width + 40 + max_edges*10 + left_space
    physical=layer_devices(ix,'l1')
    lefts = {device:left_space + n*column for n,device in enumerate(physical)}
    for d in ix['devices'].values():
        if d.get('kind')=='stack':lefts[d['id']]=min(lefts[m['device']] for m in d['members'])
    width = max(1450, left_space + len(physical)*column)
    port_sides={}
    port_colors={}
    for i,link in enumerate(physical_links):
        a,b=link['endpoints']
        da,db=ix['l1.ports'][a]['device'],ix['l1.ports'][b]['device']
        port_sides[a]=1 if lefts[da]<=lefts[db] else -1
        port_sides[b]=1 if da==db or lefts[db]<lefts[da] else -1
        color=['#1779a5','#b5681c','#287c58','#a04a92','#6a64b0','#ad574d'][i%6]
        port_colors[a]=port_colors[b]=color
    for c in extra_connections:
        a,b=c['endpoints']
        for endpoint,other in [(a,b),(b,a)]:
            if 'port' in endpoint:
                owner=endpoint_owner(endpoint,ix);remote=endpoint_owner(other,ix)
                port_sides.setdefault(endpoint['port'],1 if remote is None or lefts[owner]<=lefts[remote] else -1)
    new_anchors={}
    svg, nodes, sections = [], {}, {}
    membership_anchors, network_styles = {}, []
    binding_anchors, binding_labels, binding_styles = {}, {}, []
    escape = lambda value: html.escape(str(value),quote=True)

    def text(x,y,value,size=14,color='#23344d'):
        svg.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}">{escape(value)}</text>')

    def lines_at(x,y,lines,size=13,color='#23344d',step=18):
        for n,value in enumerate(lines):
            text(x,y+n*step,value,size,color)

    def rect(x,y,w,h,fill='white',stroke='#9fb0c4',css=''):
        svg.append(f'<rect class="{css}" x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}"/>')

    def edge(points,color,css='',attrs=''):
        d='M'+' L'.join(f'{x},{y}' for x,y in points)
        svg.append(f'<path class="{css}" d="{d}" fill="none" stroke="{color}" stroke-width="1.7" {attrs}/>')

    vpn_styles=[]
    vpns=list(ix['vpn_connections'].values()) if 'l3' in wanted else []
    vpn_rows={};vpn_networks={};vpn_devices={}
    for n,vpn in enumerate(vpns):
        for identity in vpn_members(vpn,ix):vpn_rows.setdefault(identity,[]).append(n)
        for endpoint in vpn['endpoints']:
            vpn_devices.setdefault(endpoint['device'],[]).append(n)
            for identity in endpoint['subnets']:vpn_networks.setdefault(identity,[]).append(n)
    y = 145
    if vpns:
        svg.append('<g data-vpn-layer="l3">')
        text(40,y+28,'L3 / 拠点間VPN（論理オーバーレイ）',22)
        text(40,y+51,'破線＝VPNの定義 / 稼働状態・ルーティング・FW許可は別途確認 / L1ケーブルは追加しません',12,'#60788e')
        y+=70
        for n,vpn in enumerate(vpns):
            endpoint_lines=[]
            for e in vpn['endpoints']:
                labels=[e['site']+' / '+e['device']]
                labels.append(('トンネルIF: '+e['tunnel_interface']+' / '+e.get('tunnel_address','unnumbered')) if vpn['mode']=='route_based' else 'ポリシー終端 / トンネルIFなし')
                labels+=['対象: '+s+' / '+ix['l3.subnets'][s]['cidr'] for s in e['subnets']]
                endpoint_lines.append([part for label in labels for part in wrap_label(label,64)])
            h=80+18*max(map(len,endpoint_lines))
            mode='ルート型' if vpn['mode']=='route_based' else 'ポリシー型（同一IPバージョンの両端対象を相互セレクターとして定義）'
            desc=vpn['name']+' / '+vpn['id']+' / IPsec / '+mode
            desc_lines=wrap_label(desc,max(80,int((width-120)/8)))
            extra=18*(len(desc_lines)-1);h+=extra
            attrs='data-vpn-id="'+escape(vpn['id'])+'" data-vpn-members="'+escape(json.dumps(vpn_members(vpn,ix)))+'" data-vpn-devices="'+escape(json.dumps([e['device'] for e in vpn['endpoints']]))+'"'
            svg.append(f'<g class="vpn-group vpn-{n}" {attrs} tabindex="0" role="button" aria-pressed="false" aria-label="{escape(desc)}">')
            rect(40,y,width-80,h,'#f3f0fc','#a896c1','vpn-frame')
            lines_at(56,y+25,desc_lines,15,'#614184',18)
            half=(width-160)/2
            lines_at(56,y+53+extra,endpoint_lines[0],12,'#33475b')
            lines_at(width/2+70,y+53+extra,endpoint_lines[1],12,'#33475b')
            edge([(width/2-55,y+h-20),(width/2+55,y+h-20)],'#80549b','vpn-path','stroke-dasharray="8 5"')
            text(width/2-39,y+h-27,'IPsec VPN',11,'#614184')
            svg.append('</g>')
            active=f'svg:has(.vpn-{n}:is(:hover,:focus,.vpn-selected))'
            vpn_styles.append(active+f' :is(.vpn-member-{n},.vpn-network-{n}){{opacity:1!important}}'+active+f' .vpn-member-{n} .binding-row-highlight{{display:block;fill:#eee2fc;stroke:#80549b;stroke-width:2}}'+active+f' .device-card[data-vpn-device~="{n}"] .device-frame{{stroke:#80549b;stroke-width:3}}')
            y+=h+18
        svg.append('</g>');y+=20
    for layer,group,heading,fill in specs:
        top = y
        cards = {}
        visible_cards=layer_devices(ix,layer)
        for device in visible_cards:
            d = ix['devices'][device]
            title = wrap_label(d.get('name',device),38)
            identity = wrap_label(device+' / '+d.get('role','device'),46)
            metadata = list(domain_labels[device])
            if d.get('kind')=='stack':
                identity=wrap_label(device+' / STACK（論理機器）',46)
                metadata += [part for member in d['members'] for part in wrap_label('Member '+str(member['number'])+' / '+member['device'],44)]
            if device in chassis_stacks:
                stack=ix['devices'][chassis_stacks[device]]
                member=next(m for m in stack['members'] if m['device']==device)
                metadata+=wrap_label('STACK / '+stack['id']+' / Member '+str(member['number']),44)
            if layer=='l1':
                for label,key in [('メーカー','manufacturer'),('型番','model'),('S/N','serial_number')]:
                    metadata += wrap_label(label+'：'+str(d.get(key,'未設定')),44)
                loc_labels={'site':'拠点','room':'部屋','position':'位置','rack':'ラック','rack_unit':'U'}
                for key,value in d.get('location',{}).items():
                    metadata += wrap_label(loc_labels.get(key,key)+'：'+str(value),44)
            header = 22+len(title)*21+len(identity)*17+(len(metadata)*18+12 if metadata else 0)+14
            rows = []
            for item in ix[group].values():
                if item['device']!=device:
                    continue
                # Lead with the operational value, retaining stable reference IDs below.
                if layer=='l1':
                    primary=item.get('name') or item['id'].split('.')[-1]
                    details=[item['id']]+(['STACK専用接続'] if any(item['id'] in ix['l1.links'][lid]['endpoints'] for lid in stack_link_ids) else ['MLAG peer-link'] if any(item['id'] in ix['l1.links'][lid]['endpoints'] for lid in mlag_link_ids) else [])+(['Wi-Fi 無線インターフェース'] if item.get('kind')=='wifi' else [])
                elif layer=='l2':
                    vlan_refs=interface_vlans(item)
                    primary='routed / VLANなし' if item['mode']=='routed' else 'VLAN '+(', '.join(str(ix['l2.vlans'][v]['tag']) for v in vlan_refs) or 'なし')
                    details=[item['id'],'SVI / 論理VLAN IF・物理ポートなし' if item['mode']=='svi' else 'routed / IPを直接対応付け' if item['mode']=='routed' else item['mode']+(' / untagged' if item['mode']=='access' else ' / tagged')]
                    if item.get('aggregation'):
                        agg=item['aggregation'];ports=[b['physical_port'] for b in model['bindings']['l2_to_l1'] if b['l2_interface']==item['id']]
                        details+=[agg['kind']+' / '+agg['mode']+' / '+str(len(ports))+' physical ports']
                        if agg.get('primary_port'):details.append('優先ポート（設定） / '+agg['primary_port'])
                        details+=[ix['l1.ports'][p]['device']+' / '+(ix['l1.ports'][p].get('name') or p) for p in ports]
                else:
                    primary=item['address']
                    details=[item['id'],'subnet / '+item['subnet']]
                    binding=next((b for b in model['bindings']['l3_to_l2'] if b['l3_interface']==item['id']),None)
                    if binding and ix['l2.interfaces'][binding['l2_interface']]['mode']=='svi':
                        details.append('SVI / VLAN '+str(ix['l2.vlans'][binding['vlan']]['tag'])+' / '+binding['l2_interface'])
                if layer=='l1' and item.get('connector'):
                    details.append('connector / '+item['connector'])
                title_lines=wrap_label(primary,30)
                detail_lines=[part for detail in details for part in wrap_label(detail,46)]
                height=24*len(title_lines)+18*(len(detail_lines)+sum(len(wrap_label(net['number']+' / '+net['id'],46)) for net in memberships.get((layer,item['id']),[]))+sum(len(wrap_label(binding_badge(b,layer),46)) for b in row_bindings.get((layer,item['id']),[])))+18
                rows.append((item,title_lines,detail_lines,height))
            height=header+sum(row[3] for row in rows)+12+(sum(ghost_height(c) for i,j,c in ghosts[device]) if layer=='l1' else 0)
            if not rows:
                height+=44
            cards[device]=(title,identity,metadata,header,rows,height)
        domain_lines=[]
        for domain in ix['mlag_domains'].values():
            label='MLAG / '+domain['name']+' / 独立したpeer: '+' ↔ '.join(domain['peers'])+' / pairs: '+(', '.join(' ↔ '.join(pair) for pair in domain['interface_pairs']) or '未記載')
            domain_lines.append((domain,wrap_label(label,max(60,int((width-120)/8)))))
        domain_height=sum(22+18*len(lines) for _,lines in domain_lines)
        card_top=top+62+domain_height+(20*(len(physical_links)+len(extra_connections)) if layer=='l1' else 0)
        bottom=max((card_top+c[-1] for c in cards.values()),default=card_top+44)
        bus_top=bottom+45
        bus_layout=[]
        cursor=bus_top
        for network in networks[layer]:
            labels=wrap_label(network['number']+' / '+network['label'],44)
            by=cursor+18*len(labels)+10
            bus_layout.append((by,labels,network))
            cursor=by+38
        unknown_connections=[(i,c,j) for i,c in enumerate(extra_connections) for j,e in enumerate(c['endpoints']) if 'unknown' in e] if layer=='l1' else []
        unknown_layout=[];unknown_cursor=bottom+32
        for i,c,j in unknown_connections:
            labels=[('AP未確認' if c['kind']=='wifi' else '接続先機器未確認')+' / N'+str(i+1)]+wrap_label('SSID: '+c['ssid'] if c.get('ssid') else '相手機器・ポートを特定していません',40)
            h=20+16*len(labels)
            unknown_layout.append((i,c,j,unknown_cursor,h,labels));unknown_cursor+=h+24
        route_bottom=unknown_cursor if unknown_layout else bottom
        cable_rows=[]
        extra_rows=[]
        if layer=='l1':
            cursor=route_bottom+58+24*(len(physical_links)+len(extra_connections))
            for i,link in enumerate(physical_links):
                label=f'C{i+1}  '+('STACK / ' if link['id'] in stack_link_ids else 'MLAG peer-link / ' if link['id'] in mlag_link_ids else '')+link['id']+'  |  '+link['endpoints'][0]+' ↔ '+link['endpoints'][1]+'  |  '+link.get('medium','')+' / '+link.get('speed','')
                labels=wrap_label(label,min(180,int((width-80)/7)))
                cable_rows.append((cursor,labels,link))
                cursor+=len(labels)*18+13
            for i,c in enumerate(extra_connections):
                labels=wrap_label(f'N{i+1} / '+c['id']+' / '+connection_label(c),min(180,int((width-80)/7)))
                extra_rows.append((cursor,labels,c));cursor+=len(labels)*18+13
        end=max(cursor,route_bottom+35)+16
        sections[layer]=(top,end)
        svg.append(f'<g data-layer="{layer}">')
        rect(20,top,width-40,end-top,fill,fill,'layer-panel')
        heading_x=left_space+16 if binding_records else 40
        text(heading_x,top+32,heading.replace('ケーブル','有線・Wi-Fi接続') if layer=='l1' and extra_connections else heading,22)
        if layer=='l1' and extra_connections:text(heading_x,top+51,'有線＝実線 / Wi-Fi＝波線 / 橙色・?＝未確認（有線は一点鎖線）/ 紫破線＝層間対応',11,'#60788e')
        domain_y=top+52
        for domain,labels in domain_lines:
            h=18*len(labels)+16
            svg.append(f'<g class="equipment-domain" data-domain-id="{escape(domain["id"])}" data-domain-devices="{escape(json.dumps(domain["peers"]))}" tabindex="0" role="button" aria-label="{escape(domain["name"]+" / MLAG / 独立管理")}">')
            rect(40,domain_y,width-80,h,'#fff6e9','#c39753','domain-frame')
            lines_at(52,domain_y+21,labels,12,'#856026',18);svg.append('</g>');domain_y+=h+6
        for device,(title,identity,metadata,header,rows,height) in cards.items():
            left=lefts[device]
            right=left+card_width
            name=ix['devices'][device].get('name',device)
            svg.append(f'<g class="device-card" data-vpn-device="{" ".join(str(n) for n in vpn_devices.get(device,[]))}" data-device="{escape(device)}" data-device-layer="{layer}" data-stack-id="{escape(device if ix['devices'][device].get('kind')=='stack' else chassis_stacks.get(device,''))}" tabindex="0" role="button" aria-label="{escape(name)} / {layer.upper()}">')
            rect(left,card_top,card_width,height,css='device-frame')
            baseline=card_top+26
            lines_at(left+16,baseline,title,16,step=21)
            baseline+=21*len(title)
            lines_at(left+16,baseline,identity,11,'#72869b',17)
            baseline+=17*len(identity)+8
            lines_at(left+16,baseline,metadata,12,'#526980',18)
            row_top=card_top+header
            for item,title_lines,detail_lines,row_height in rows:
                anchor=row_top+row_height/2
                side=port_sides.get(item['id'],1) if layer=='l1' else 1
                anchor_x=right if side==1 else left
                nodes[(layer,item['id'])]={'left':left,'right':right,'anchor_x':anchor_x,'y':anchor,'device':device,'side':side,'slot':len([n for (l,k),n in nodes.items() if l==layer and n['device']==device])}
                member_classes=' '.join(['vpn-member-'+str(n) for n in vpn_rows.get(item['id'],[])] if layer=='l3' else [])+' '+' '.join(['member-'+net['key'] for net in memberships.get((layer,item['id']),[])]+['binding-row-'+b['key'] for b in row_bindings.get((layer,item['id']),[])])
                svg.append(f'<g class="interface-row {member_classes}" data-element-id="{escape(item["id"])}" data-owner="{escape(device)}" data-interface-mode="{escape(item.get('mode','ip' if layer=='l3' else 'physical'))}" tabindex="0" role="button" aria-pressed="false" aria-label="{escape(layer.upper()+" / "+item["id"]+" / "+"".join(title_lines)+" / 層間対応を追跡")}" data-anchor-y="{anchor}" data-anchor-x="{anchor_x}">')
                rect(left+5,row_top+3,card_width-10,row_height-6,'transparent','none','interface-hit')
                rect(left+5,row_top+3,card_width-10,row_height-6,'#f1eafa','#8665a6','binding-row-highlight')
                svg.append(f'<title>{escape(item["id"])}</title>')
                edge([(left+12,row_top),(right-12,row_top)],'#e0e7ee','row-separator')
                for line_no,line in enumerate(title_lines):
                    svg.append(f'<text class="interface-primary" x="{left+16}" y="{row_top+24+line_no*24}" font-size="18" font-weight="700" fill="#23344d">{escape(line)}</text>')
                lines_at(left+16,row_top+24+24*len(title_lines),detail_lines,11,'#60788e')
                member_top=row_top+24+24*len(title_lines)+18*len(detail_lines)
                for net in memberships.get((layer,item['id']),[]):
                    member_lines=wrap_label(net['number']+' / '+net['id'],46)
                    member_y=member_top-4
                    membership_anchors[(layer,net['key'],item['id'])]=(right,member_y)
                    for line_no,line in enumerate(member_lines):
                        svg.append(f'<text class="membership-label member-{net["key"]}" tabindex="0" role="img" aria-label="{escape(net["label"])}" x="{left+16}" y="{member_y+4+line_no*18}" font-size="12" fill="{net["color"]}">{escape(line)}</text>')
                    member_top+=18*len(member_lines)
                    svg.append(f'<circle class="membership-anchor member-{net["key"]}" data-membership-network="{escape(net["id"])}" data-membership-interface="{escape(item["id"])}" cx="{right}" cy="{member_y}" r="3.5" fill="white" stroke="{net["color"]}" stroke-width="1.5"/>')
                for record in row_bindings.get((layer,item['id']),[]):
                    badge_lines=wrap_label(binding_badge(record,layer),46)
                    badge_y=member_top-4
                    binding_anchors[(record['key'],layer)]=(left,badge_y)
                    svg.append(f'<g class="binding-badge binding-{record["key"]}" data-binding-key="{record["key"]}" tabindex="0" role="button" aria-pressed="false" aria-label="{escape(record["label"])}">')
                    lines_at(left+16,badge_y+4,badge_lines,11,'#765194',18)
                    svg.append(f'<circle class="binding-anchor" data-binding-key="{record["key"]}" data-binding-layer="{layer}" data-binding-element="{escape(item["id"])}" cx="{left}" cy="{badge_y}" r="3.5" fill="white" stroke="#8665a6"/>')
                    svg.append('</g>')
                    member_top+=18*len(badge_lines)
                if layer=='l1':
                    svg.append(f'<circle class="interface-anchor" data-port-id="{escape(item["id"])}" cx="{anchor_x}" cy="{anchor}" r="4" fill="white" stroke="{port_colors.get(item["id"],"#63849a") if layer=="l1" else "#63849a"}" stroke-width="1.5"/>')
                svg.append('</g>')
                row_top+=row_height
            if not rows:
                label={'l1':'物理ポートなし','l2':'L2インターフェースなし','l3':'L3インターフェースなし'}[layer]
                text(left+16,row_top+25,label,12,'#8192a5')
            if layer=='l1':
                ghost_top=row_top+(44 if not rows else 0)
                for ghost_no,(i,j,c) in enumerate(ghosts[device]):
                    other=c['endpoints'][1-j];remote=endpoint_owner(other,ix)
                    side=1 if remote is None or lefts[device]<=lefts[remote] else -1
                    ax=right if side==1 else left;ay=ghost_top+30
                    labels=['ポート／無線IF未確認 / N'+str(i+1)]+wrap_label(c['id'],44)
                    svg.append(f'<g class="unresolved-endpoint" data-connection-id="{escape(c["id"])}" role="img" aria-label="{escape(device+" / ポート／無線IF未確認")}">')
                    rect(left+8,ghost_top+3,card_width-16,ghost_height(c)-6,'#fff7e8','#c2822b')
                    lines_at(left+16,ghost_top+23,labels,12,'#915a15',16)
                    svg.append(f'<circle cx="{ax}" cy="{ay}" r="6" fill="#fff7e8" stroke="#c2822b"/>')
                    svg.append('</g>')
                    new_anchors[(c['id'],j)]={'left':left,'right':right,'anchor_x':ax,'y':ay,'device':device,'side':side,'slot':len(rows)+ghost_no}
                    ghost_top+=ghost_height(c)
            svg.append('</g>')
        if layer=='l1':
            layer_nodes={key:n for (l,key),n in nodes.items() if l=='l1'}
            boxes=[(lefts[d],card_top,lefts[d]+card_width,card_top+cards[d][-1]) for d in cards]
            for i,c,j,uy,unknown_height,unknown_labels in unknown_layout:
                known=c['endpoints'][1-j];owner=endpoint_owner(known,ix)
                x=lefts[owner]+16
                label=('AP未確認' if c['kind']=='wifi' else '接続先機器未確認')+' / N'+str(i+1)
                svg.append(f'<g class="unknown-peer" data-connection-id="{escape(c["id"])}" role="img" aria-label="{escape(label)}">')
                rect(x,uy,300,unknown_height,'#fff7e8','#c2822b')
                lines_at(x+12,uy+23,unknown_labels,12,'#915a15',16)
                svg.append('</g>');boxes.append((x,uy,x+300,uy+unknown_height))
                new_anchors[(c['id'],j)]={'left':x,'right':x+300,'anchor_x':x,'y':uy+unknown_height/2,'device':('unknown',c['id']),'side':-1,'slot':0}
            routed_extra=[]
            for c in extra_connections:
                keys=[]
                for j,e in enumerate(c['endpoints']):
                    key=('connection',c['id'],j);keys.append(key)
                    layer_nodes[key]=dict(layer_nodes[e['port']]) if 'port' in e else new_anchors[(c['id'],j)]
                routed_extra.append({'id':c['id'],'endpoints':keys})
            routes=route_cables(physical_links+routed_extra,layer_nodes,boxes,card_top,route_bottom)
            for list_y,labels,link in cable_rows:
                routed=routes[link['id']]
                a,b=link['endpoints']
                description=('STACK / ' if link['id'] in stack_link_ids else 'MLAG peer-link / ' if link['id'] in mlag_link_ids else '')+link['id']+' / '+a+' ↔ '+b+' / '+link.get('medium','')+' / '+link.get('speed','')
                svg.append(f'<g class="physical-cable-group" data-cable-id="{escape(link["id"])}" tabindex="0" role="img" aria-label="{escape(description)}">')
                svg.append(f'<title>{escape(description)}</title>')
                attrs=f'data-from="{escape(a)}" data-to="{escape(b)}" stroke-linecap="round" stroke-linejoin="round"'
                edge(routed['points'],routed['color'],'physical-cable',attrs)
                horizontal=[(p,q) for p,q in segments(routed['points']) if p[1]==q[1]]
                if horizontal:
                    p,q=max(horizontal,key=lambda pair:abs(pair[1][0]-pair[0][0]))
                    label_x=(p[0]+q[0])/2
                    svg.append(f'<text class="cable-number" x="{label_x}" y="{p[1]-7}" text-anchor="middle" font-size="11" fill="{routed["color"]}" paint-order="stroke" stroke="{fill}" stroke-width="4">{routed["number"]}{' / STACK' if link['id'] in stack_link_ids else ' / MLAG peer' if link['id'] in mlag_link_ids else ''}</text>')
                lines_at(40,list_y,labels,12,routed['color'])
                svg.append('</g>')
            for i,(list_y,labels,c) in enumerate(extra_rows):
                routed=routes[c['id']];uncertain=c['status']!='confirmed'
                color='#b47720' if uncertain else '#147d78' if c['kind']=='wifi' else routed['color']
                description=c['id']+' / '+connection_label(c)
                svg.append(f'<g class="l1-connection kind-{c["kind"]} status-{c["status"]}" data-connection-id="{escape(c["id"])}" data-connection-kind="{c["kind"]}" data-connection-status="{c["status"]}" tabindex="0" role="img" aria-label="{escape(description)}">')
                svg.append(f'<title>{escape(description)}</title>')
                attrs='stroke-linecap="round" stroke-linejoin="round"'+(' stroke-dasharray="10 3 2 3"' if uncertain and c['kind']=='wired' else '')
                if c['kind']=='wifi':
                    svg.append(f'<path class="connection-path wifi-wave" d="{wave_path(routed["points"])}" fill="none" stroke="{color}" stroke-width="1.9" {attrs}/>')
                else:edge(routed['points'],color,'connection-path wired-path',attrs)
                horizontal=[(a,b) for a,b in segments(routed['points']) if a[1]==b[1]]
                if horizontal:
                    a,b=max(horizontal,key=lambda pair:abs(pair[1][0]-pair[0][0]));x=(a[0]+b[0])/2
                    svg.append(f'<text class="connection-number" x="{x}" y="{a[1]-8}" text-anchor="middle" font-size="11" fill="{color}" paint-order="stroke" stroke="{fill}" stroke-width="4">N{i+1} / {"Wi-Fi" if c["kind"]=="wifi" else "有線"}{" / ? 未確認" if uncertain else ""}</text>')
                lines_at(40,list_y,labels,12,color);svg.append('</g>')
        else:
            # Lower rows leave nearest the card; upper rows use outer tracks.
            # This avoids the staircase crossings of relation-by-relation lanes.
            departures={device:[] for device in devices}
            for by,labels,net in bus_layout:
                for member in net['members']:
                    node=nodes[(layer,member)]
                    x,sy=membership_anchors[(layer,net['key'],member)]
                    departures[node['device']].append((sy,net['key'],member))
            lanes={}
            for device,entries in departures.items():
                for rank,(sy,key,member) in enumerate(sorted(entries,reverse=True)):
                    lanes[(key,member)]=lefts[device]+card_width+18+rank*10
            text(heading_x,top+51,'V＝VLAN / S＝サブネット / B＝機器内ブリッジ（VLAN別に転送）',10,'#60788e')
            for by,labels,net in bus_layout:
                key,color=net['key'],net['color']
                description=net['number']+' / '+net['label']+' / 所属：'+(', '.join(net['members']) or 'なし')
                svg.append(f'<g class="network-group network-{key} {" ".join("vpn-network-"+str(n) for n in vpn_networks.get(net["id"],[])) if layer=="l3" else ""}" data-network-id="{escape(net["id"])}" data-network-kind="{net["kind"]}" tabindex="0" role="img" aria-label="{escape(description)}">')
                svg.append(f'<title>{escape(description)}</title>')
                xs=[lanes[(key,member)] for member in net['members']]
                def logical_edge(points,css,attrs=''):
                    # A background casing makes unavoidable crossings non-junctions.
                    edge(points,fill,'relation-casing','stroke-linejoin="round" aria-hidden="true" style="stroke-width:6;pointer-events:none"')
                    edge(points,color,css,attrs+' stroke-linejoin="round"')
                if xs:
                    logical_edge([(min(xs)-7,by),(max(xs)+7,by)],'relation-bus')
                for member in net['members']:
                    x,sy=membership_anchors[(layer,key,member)]
                    lane=lanes[(key,member)]
                    attrs=f'data-endpoint="{escape(member)}" data-network="{escape(net["id"])}"'
                    logical_edge([(x,sy),(lane,sy),(lane,by)],'relation-branch',attrs)
                    svg.append(f'<circle class="network-junction" cx="{lane}" cy="{by}" r="2.8" fill="{color}"/>')
                lines_at(40,by-10-18*(len(labels)-1),labels,12,color)
                if not net['members']:
                    text(40,by+16,'所属インターフェースなし',11,'#8192a5')
                svg.append('</g>')
                active=f':is(.network-{key},.membership-label.member-{key},.membership-anchor.member-{key}):is(:hover,:focus)'
                scope=f'[data-layer="{layer}"]'
                trigger=f'svg:has({active}):not(:has({scope} :is(.network-group,.membership-label,.membership-anchor):hover:not(.network-{key}):not(.member-{key})))'
                network_styles.append(f'{trigger} {scope} .network-group:not(.network-{key})'+'{opacity:.15}')
                network_styles.append(f'{trigger} {scope} .interface-row:not(.member-{key})'+'{opacity:.22}')
                network_styles.append(f'{trigger} {scope} .membership-label.member-{key}'+'{font-weight:bold}')
                network_styles.append(f'{trigger} {scope} .network-{key} :is(.relation-branch,.relation-bus)'+'{stroke-width:3}')
                network_styles.append(f'{trigger} {scope} :is(.membership-label,.membership-anchor):not(.member-{key})'+'{opacity:.22}')
        svg.append('</g>')
        outgoing=[b for b in binding_records if b['upper']==layer]
        label_space=Counter()
        per_device=Counter()
        for record in outgoing:
            device=record['device']
            labels=wrap_label(record['label'],46)
            binding_labels[record['key']]=(end+52+label_space[device],labels)
            label_space[device]+=len(labels)*15+15
            per_device[device]+=1
        y=end+max(35,70+max(label_space.values(),default=0),85+12*max(per_device.values(),default=0)) if outgoing else end+35
    # Keep source and target legs in separate tracks; fan out near the rows in
    # their vertical order and put unavoidable crossings in the interlayer gap.
    routed={}
    offsets=Counter()
    for upper,lower,kind,ak,bk in binding_specs:
        records=[b for b in binding_records if b['kind']==kind]
        for device in devices:
            group=[b for b in records if b['device']==device]
            origin=lefts[device]-20
            source_order=sorted(group,key=lambda b:binding_anchors[(b['key'],upper)][1],reverse=True)
            target_order=sorted(group,key=lambda b:binding_anchors[(b['key'],lower)][1])
            source_lanes={b['key']:origin-(offsets[device]+n)*10 for n,b in enumerate(source_order)}
            target_lanes={b['key']:lefts[nodes[(lower,b['target'])]['device']]-20-(offsets[device]+len(group)+n)*10 for n,b in enumerate(target_order)}
            for n,record in enumerate(group):
                key=record['key']
                a=binding_anchors[(key,upper)]
                b=binding_anchors[(key,lower)]
                gap=sections[upper][1]+54+n*12
                routed[key]=compact_path([a,(source_lanes[key],a[1]),(source_lanes[key],gap),(target_lanes[key],gap),(target_lanes[key],b[1]),b])
            offsets[device]+=2*len(group)
    for upper,lower,kind,ak,bk in binding_specs:
        if not any(b['kind']==kind for b in binding_records):
            continue
        svg.append(f'<g data-binding="{kind}">')
        text(left_space+8,sections[upper][1]+24,'層間対応 / '+kind+' / M番号・線を選択して両端を強調',12,'#765194')
        for record in [b for b in binding_records if b['kind']==kind]:
            key=record['key']
            svg.append(f'<g class="binding-group binding-{key}" data-binding-key="{key}" data-binding-kind="{kind}" tabindex="0" role="button" aria-pressed="false" aria-label="{escape(record["label"])}">')
            svg.append(f'<title>{escape(record["label"])}</title>')
            edge(routed[key],'#f8fafc','binding-casing','style="stroke-width:6;pointer-events:none" aria-hidden="true" stroke-linejoin="round"')
            edge(routed[key],'transparent','binding-hit','style="stroke-width:14;pointer-events:stroke" aria-hidden="true"')
            attrs=f'data-binding-key="{key}" data-from="{escape(record["source"])}" data-to="{escape(record["target"])}" data-from-layer="{upper}" data-to-layer="{lower}" stroke-dasharray="5 5" stroke-linejoin="round"'
            edge(routed[key],'#8665a6','binding-edge',attrs)
            list_y,labels=binding_labels[key]
            lines_at(lefts[record['device']]+8,list_y,labels,10,'#765194',15)
            svg.append('</g>')
            # SVG-only hover/focus also works in exported diagrams. In the web
            # app a clicked selection stays active until cleared or redrawn.
            candidate=f'.binding-{key}:is(:hover,:focus)'
            transient=f'svg:not(.trace-active):not(:has(.selected-binding)):has({candidate}):not(:has(:is(.binding-group,.binding-badge):hover:not(.binding-{key})))'
            persistent=f'svg:has(.binding-{key}.selected-binding)'
            trigger=f':is({persistent},{transient})'
            binding_styles.append(f'{trigger} .interface-row'+'{opacity:.18!important}')
            binding_styles.append(f'{trigger} .binding-row-{key}'+'{opacity:1!important}')
            binding_styles.append(f'{trigger} .binding-row-{key} .binding-row-highlight'+'{display:block;stroke-width:2}')
            binding_styles.append(f'{trigger} .binding-group:not(.binding-{key})'+'{opacity:.12}')
            binding_styles.append(f'{trigger} .binding-group.binding-{key}'+'{opacity:1}')
            binding_styles.append(f'{trigger} .binding-group.binding-{key} .binding-edge'+'{stroke-width:3.5;stroke:#6f359e}')
            binding_styles.append(f'{trigger} .binding-badge.binding-{key} text'+'{font-weight:bold}')
            binding_styles.append(f'{trigger} :is(.network-group,.physical-cable-group,.l1-connection)'+'{opacity:.12!important}')
        svg.append('</g>')
    y=max(end for top,end in sections.values())+42
    if 'l3' in wanted:
        text(40,y,'L3経路 / 次ホップの指定（通信許可を意味しません）',19)
        y+=28
        for route in model['l3'].get('routes',[]):
            labels=wrap_label(route['device']+' / '+route['interface']+' : '+route['destination']+' → '+route['next_hop'],120)
            lines_at(40,y,labels,13,step=18)
            y+=len(labels)*18+8
    for note in list(context_notes or [])+model.get('notes',[]):
        labels=wrap_label('注：'+note,120)
        lines_at(40,y+18,labels,12,step=18)
        y+=len(labels)*18+8
    text(40,y+28,'一機器一枠 / 枠内の行・接続点＝ポートやインターフェース / 実線＝各層の関係 / 紫破線＝層間対応',12)
    height=y+55
    network_css=''.join(network_styles+vpn_styles)
    binding_css=''.join(binding_styles)
    header=f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><style>.vpn-group{{cursor:pointer;outline:none}}.vpn-group:is(:hover,:focus,.vpn-selected) .vpn-frame{{stroke:#80549b;stroke-width:3}}.vpn-group:is(:hover,:focus,.vpn-selected) .vpn-path{{stroke-width:4}}.vpn-related .binding-row-highlight{{display:block;fill:#eee2fc;stroke:#80549b;stroke-width:2}}.vpn-related.binding-group .binding-edge{{stroke:#80549b;stroke-width:3.5}}text{{font-family:"Yu Gothic",Meiryo,sans-serif}}.l1-connection{{cursor:crosshair;outline:none}}.l1-connection:is(:hover,:focus) .connection-path{{stroke-width:3.5}}svg:has(.l1-connection:is(:hover,:focus)) .l1-connection:not(:hover):not(:focus){{opacity:.22}}.physical-cable-group{{cursor:crosshair;outline:none}}.physical-cable-group:is(:hover,:focus) .physical-cable{{stroke-width:3.5}}svg:has(.physical-cable-group:is(:hover,:focus)) .physical-cable-group:not(:hover):not(:focus){{opacity:.22}}.network-group,.membership-label{{cursor:crosshair;outline:none}}.network-group:is(:hover,:focus) .relation-branch,.network-group:is(:hover,:focus) .relation-bus{{stroke-width:3}}{network_css}.binding-row-highlight{{display:none}}.binding-group,.binding-badge{{cursor:pointer;outline:none}}{binding_css}.interface-hit{{pointer-events:all}}.interface-row{{cursor:pointer;outline:none}}.interface-row:focus>.binding-row-highlight{{display:block;stroke:#177b69;stroke-width:2}}svg.trace-active .interface-row{{opacity:.18!important}}svg.trace-active .interface-row.trace-row{{opacity:1!important}}svg.trace-active .trace-row .binding-row-highlight{{display:block;stroke-width:2;stroke:#8665a6}}svg.trace-active .trace-root .binding-row-highlight{{fill:#e4f5ee;stroke:#177b69;stroke-width:3}}svg.trace-active .binding-group{{opacity:.12!important}}svg.trace-active .binding-group.trace-edge{{opacity:1!important}}svg.trace-active .trace-edge .binding-edge{{stroke:#6f359e;stroke-width:3.5}}svg.trace-active .binding-badge.trace-edge text{{font-weight:bold}}svg.trace-active :is(.network-group,.physical-cable-group){{opacity:.12!important}}</style><rect width="100%" height="100%" fill="#f8fafc"/>'
    title=f'<text x="40" y="43" font-family="Meiryo,sans-serif" font-size="27">{escape(model.get("name","LAN"))}</text><text x="40" y="76" font-family="Meiryo,sans-serif" font-size="14">{escape(model.get("scope",""))}</text><text x="40" y="106" font-family="Meiryo,sans-serif" font-size="13">YAMLから自動生成 / 機器ごとに集約し、ポート・インターフェース単位の接続を表示</text>'
    return header+title+'\n'+'\n'.join(svg)+'</svg>\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('-o', '--output', type=Path)
    parser.add_argument('--watch', action='store_true', help='regenerate on input changes; Ctrl+C to stop')
    parser.add_argument('--site', help='draw only this site')
    parser.add_argument('--group', help='draw only this device group')
    parser.add_argument('--device', action='append', default=[], help='device ID; repeatable')
    parser.add_argument('--focus-layer', choices=['l1','l2','l3'])
    parser.add_argument('--focus-id')
    args = parser.parse_args()
    def generate_once():
        try:
            output = args.output or args.input.with_suffix('.svg')
            if output.resolve() == args.input.resolve():
                raise ModelError('output must differ from input YAML')
            model,ix = load_model(args.input.read_text(encoding='utf-8-sig'),with_index=True)
            if bool(args.focus_layer)!=bool(args.focus_id):
                raise ModelError('--focus-layerと--focus-idは一緒に指定してください')
            scope=ViewScope(site=args.site,group=args.group,device_ids=args.device,trace_root=TraceRoot(layer=args.focus_layer,id=args.focus_id) if args.focus_layer else None)
            projected,display,_=prepare_view(model,ix,scope)
            if display['status']!='ready':raise ModelError(display['message'])
            drawing = render(projected,context_notes=display['context_notes'])
            # Validation completes before touching the existing drawing.
            output.write_text(drawing, encoding='utf-8')
            print(f'Generated: {output.resolve()}', flush=True)
            return 0
        except (ModelError, KeyError, TypeError, ValueError, OSError, yaml.YAMLError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr, flush=True)
            return 1

    if not args.watch:
        return generate_once()
    print('Watching YAML; Ctrl+C to stop. Invalid updates keep the last valid SVG.', flush=True)
    last_content = None
    try:
        while True:
            try:
                content = args.input.read_bytes()
            except OSError:
                content = b''
            if content != last_content:
                time.sleep(0.2)  # allow editors to finish saving
                generate_once()
                last_content = content
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    sys.exit(main())
