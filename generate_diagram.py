"""Render the shared network model as one equipment card per device per layer."""
import argparse
import html
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

import yaml
from network_model import ModelError, validate, load_model


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


def render(model, layers=None, show_bindings=True):
    ix = validate(model)
    wanted = tuple(layers) if layers is not None else ('l3', 'l2', 'l1')
    if not wanted or len(set(wanted)) != len(wanted) or any(l not in ('l1','l2','l3') for l in wanted):
        raise ModelError('表示するレイヤーはl1・l2・l3から選択してください')
    devices = list(ix['devices'])
    specs = [('l3','l3.interfaces','L3 / IPインターフェース・サブネット','#eaf3fc'),
             ('l2','l2.interfaces','L2 / VLAN・ブリッジ','#edf6ef'),
             ('l1','l1.ports','L1 / 物理ポート・ケーブル','#f0eff7')]
    specs = [spec for spec in specs if spec[0] in wanted]
    colors = {v:c for v,c in zip(ix['l2.vlans'], ['#1676b5','#b56316','#18856c','#af3982','#5e56ba']*100)}
    relations = {}
    for layer, group, _, _ in specs:
        items = list(ix[group].values())
        if layer == 'l3':
            relations[layer] = [(s['id']+' / '+s['cidr'],[i['id'] for i in items if i['subnet']==s['id']],'#1676b5') for s in ix['l3.subnets'].values()]
        elif layer == 'l2':
            relations[layer] = [(v['id']+' / VLAN '+str(v['tag'])+' / '+v.get('label',''),
                                 [i['id'] for i in items if v['id'] in ([i['untagged_vlan']] if i['mode']=='access' else i['tagged_vlans'])],colors[v['id']]) for v in ix['l2.vlans'].values()]
            relations[layer] += [(b['id']+' / VLAN別に転送',b['members'],'#48794b') for b in ix['l2.bridges'].values()]
        else:
            relations[layer] = []  # Physical cables are independent point-to-point paths.
    physical_links=list(ix['l1.links'].values())
    physical_degree=Counter(ix['l1.ports'][p]['device'] for link in physical_links for p in link['endpoints'])
    max_edges = max([max(Counter(ix[group][m]['device'] for _,members,_ in relations[layer] for m in members).values(),default=0) for layer,group,_,_ in specs]+[max(physical_degree.values(),default=1) if 'l1' in wanted else 1])
    binding_specs = [('l3','l2','l3_to_l2','l3_interface','l2_interface'),('l2','l1','l2_to_l1','l2_interface','physical_port')]
    max_bindings = max([max(Counter(ix[upper+'.interfaces'][b[ak]]['device'] for b in model['bindings'][key]).values(),default=0) for upper,lower,key,ak,bk in binding_specs if upper in wanted and lower in wanted and show_bindings]+[1])
    card_width = 340
    left_space = max(60, 32 + max_bindings*7)
    column = card_width + 32 + max_edges*7 + left_space
    lefts = {device:left_space + n*column for n,device in enumerate(devices)}
    width = max(1450, left_space + len(devices)*column)
    port_sides={}
    port_colors={}
    for i,link in enumerate(physical_links):
        a,b=link['endpoints']
        da,db=ix['l1.ports'][a]['device'],ix['l1.ports'][b]['device']
        port_sides[a]=1 if lefts[da]<=lefts[db] else -1
        port_sides[b]=1 if da==db or lefts[db]<lefts[da] else -1
        color=['#1779a5','#b5681c','#287c58','#a04a92','#6a64b0','#ad574d'][i%6]
        port_colors[a]=port_colors[b]=color
    svg, nodes, sections = [], {}, {}
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

    y = 145
    for layer,group,heading,fill in specs:
        top = y
        cards = {}
        for device in devices:
            d = ix['devices'][device]
            title = wrap_label(d.get('name',device),38)
            identity = wrap_label(device+' / '+d.get('role','device'),46)
            metadata = []
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
                details = ([item.get('name',item['id'].split('.')[-1])] if layer=='l1' else
                           ['access / '+item['untagged_vlan']] if layer=='l2' and item['mode']=='access' else
                           ['trunk / '+', '.join(item['tagged_vlans'])] if layer=='l2' else
                           [item['address'],'subnet / '+item['subnet']])
                if layer=='l1' and item.get('connector'):
                    details.append('connector / '+item['connector'])
                title_lines=wrap_label(item['id'],43)
                detail_lines=[part for detail in details for part in wrap_label(detail,46)]
                height=18*(len(title_lines)+len(detail_lines))+18
                rows.append((item,title_lines,detail_lines,height))
            height=header+sum(row[3] for row in rows)+12
            if not rows:
                height+=44
            cards[device]=(title,identity,metadata,header,rows,height)
        card_top=top+62+(20*len(physical_links) if layer=='l1' else 0)
        bottom=max(card_top+c[-1] for c in cards.values())
        bus_top=bottom+45
        bus_layout=[]
        cursor=bus_top
        for label,members,color in relations[layer]:
            labels=wrap_label(label,44)
            by=cursor+18*len(labels)+10
            bus_layout.append((by,labels,members,color,label))
            cursor=by+24
        cable_rows=[]
        if layer=='l1':
            cursor=bottom+58+24*len(physical_links)
            for i,link in enumerate(physical_links):
                label=f'C{i+1}  '+link['id']+'  |  '+link['endpoints'][0]+' ↔ '+link['endpoints'][1]+'  |  '+link.get('medium','')+' / '+link.get('speed','')
                labels=wrap_label(label,min(180,int((width-80)/7)))
                cable_rows.append((cursor,labels,link))
                cursor+=len(labels)*18+13
        end=max(cursor,bottom+35)+16
        sections[layer]=(top,end)
        svg.append(f'<g data-layer="{layer}">')
        rect(20,top,width-40,end-top,fill,fill,'layer-panel')
        text(40,top+32,heading,22)
        for device,(title,identity,metadata,header,rows,height) in cards.items():
            left=lefts[device]
            right=left+card_width
            name=ix['devices'][device].get('name',device)
            svg.append(f'<g class="device-card" data-device="{escape(device)}" data-device-layer="{layer}" tabindex="0" role="button" aria-label="{escape(name)} / {layer.upper()}">')
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
                svg.append(f'<g class="interface-row" data-element-id="{escape(item["id"])}" data-owner="{escape(device)}" data-anchor-y="{anchor}" data-anchor-x="{anchor_x}">')
                svg.append(f'<title>{escape(item["id"])}</title>')
                edge([(left+12,row_top),(right-12,row_top)],'#e0e7ee','row-separator')
                lines_at(left+16,row_top+21,title_lines,13)
                lines_at(left+16,row_top+21+18*len(title_lines),detail_lines,12,'#60788e')
                svg.append(f'<circle class="interface-anchor" data-port-id="{escape(item["id"])}" cx="{anchor_x}" cy="{anchor}" r="4" fill="white" stroke="{port_colors.get(item["id"],"#63849a") if layer=="l1" else "#63849a"}" stroke-width="1.5"/>')
                svg.append('</g>')
                row_top+=row_height
            if not rows:
                label={'l1':'物理ポートなし','l2':'L2インターフェースなし','l3':'L3インターフェースなし'}[layer]
                text(left+16,row_top+25,label,12,'#8192a5')
            svg.append('</g>')
        if layer=='l1':
            layer_nodes={key:n for (l,key),n in nodes.items() if l=='l1'}
            boxes=[(lefts[d],card_top,lefts[d]+card_width,card_top+cards[d][-1]) for d in devices]
            routes=route_cables(physical_links,layer_nodes,boxes,card_top,bottom)
            for list_y,labels,link in cable_rows:
                routed=routes[link['id']]
                a,b=link['endpoints']
                description=link['id']+' / '+a+' ↔ '+b+' / '+link.get('medium','')+' / '+link.get('speed','')
                svg.append(f'<g class="physical-cable-group" data-cable-id="{escape(link["id"])}" tabindex="0" role="img" aria-label="{escape(description)}">')
                svg.append(f'<title>{escape(description)}</title>')
                attrs=f'data-from="{escape(a)}" data-to="{escape(b)}" stroke-linecap="round" stroke-linejoin="round"'
                edge(routed['points'],routed['color'],'physical-cable',attrs)
                horizontal=[(p,q) for p,q in segments(routed['points']) if p[1]==q[1]]
                if horizontal:
                    p,q=max(horizontal,key=lambda pair:abs(pair[1][0]-pair[0][0]))
                    label_x=(p[0]+q[0])/2
                    svg.append(f'<text class="cable-number" x="{label_x}" y="{p[1]-7}" text-anchor="middle" font-size="11" fill="{routed["color"]}" paint-order="stroke" stroke="{fill}" stroke-width="4">{routed["number"]}</text>')
                lines_at(40,list_y,labels,12,routed['color'])
                svg.append('</g>')
        else:
            lanes=Counter()
            for by,labels,members,color,label in bus_layout:
                xs=[]
                for member in members:
                    node=nodes[(layer,member)]
                    lane=node['right']+18+lanes[node['device']]*7
                    lanes[node['device']]+=1
                    edge([(node['right'],node['y']),(lane,node['y']),(lane,by)],color,'relation-branch',f'data-endpoint="{escape(member)}"')
                    xs.append(lane)
                    svg.append(f'<circle cx="{lane}" cy="{by}" r="2.8" fill="{color}"/>')
                if xs:
                    edge([(min(xs)-7,by),(max(xs)+7,by)],color,'relation-bus')
                lines_at(40,by-10-18*(len(labels)-1),labels,12,color)
        svg.append('</g>')
        upper_bindings=[b for upper,lower,key,ak,bk in binding_specs if upper==layer and lower in wanted and show_bindings for b in model['bindings'][key]]
        label_space=Counter()
        for binding in upper_bindings:
            ak='l3_interface' if layer=='l3' else 'l2_interface'
            bk='l2_interface' if layer=='l3' else 'physical_port'
            label=binding[ak]+' → '+binding[bk]+(' / '+binding['vlan'] if 'vlan' in binding else '')
            label_space[ix[group][binding[ak]]['device']]+=len(wrap_label(label,46))*15+12
        y=end+(65+max(label_space.values()) if label_space else 35)
    if show_bindings:
        for upper,lower,key,ak,bk in binding_specs:
            if upper not in sections or lower not in sections:
                continue
            svg.append(f'<g data-binding="{key}">')
            text(40,sections[upper][1]+24,'層間対応 / '+key,13,'#765194')
            counts=Counter()
            label_offsets=Counter()
            for binding in model['bindings'][key]:
                a,b=nodes[(upper,binding[ak])],nodes[(lower,binding[bk])]
                device=a['device']
                lane=a['left']-32-counts[device]*7
                label=binding[ak]+' → '+binding[bk]+(' / '+binding['vlan'] if 'vlan' in binding else '')
                attrs=f'data-from="{escape(binding[ak])}" data-to="{escape(binding[bk])}" stroke-dasharray="5 5"'
                edge([(a['left'],a['y']),(lane,a['y']),(lane,b['y']),(b['left'],b['y'])],'#8665a6','binding-edge',attrs)
                for node in (a,b):
                    svg.append(f'<circle cx="{node["left"]}" cy="{node["y"]}" r="2.5" fill="#8665a6"/>')
                labels=wrap_label(label,46)
                lines_at(a['left']+8,sections[upper][1]+46+label_offsets[device],labels,10,'#765194',15)
                label_offsets[device]+=len(labels)*15+12
                counts[device]+=1
            svg.append('</g>')
    y=max(end for top,end in sections.values())+42
    if 'l3' in wanted:
        text(40,y,'L3経路 / 次ホップの指定（通信許可を意味しません）',19)
        y+=28
        for route in model['l3'].get('routes',[]):
            labels=wrap_label(route['device']+' / '+route['interface']+' : '+route['destination']+' → '+route['next_hop'],120)
            lines_at(40,y,labels,13,step=18)
            y+=len(labels)*18+8
    for note in model.get('notes',[]):
        labels=wrap_label('注：'+note,120)
        lines_at(40,y+18,labels,12,step=18)
        y+=len(labels)*18+8
    text(40,y+28,'一機器一枠 / 枠内の行・接続点＝ポートやインターフェース / 実線＝各層の関係 / 紫破線＝層間対応',12)
    height=y+55
    header=f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><style>text{{font-family:"Yu Gothic",Meiryo,sans-serif}}.physical-cable-group{{cursor:crosshair;outline:none}}.physical-cable-group:is(:hover,:focus) .physical-cable{{stroke-width:3.5}}svg:has(.physical-cable-group:is(:hover,:focus)) .physical-cable-group:not(:hover):not(:focus){{opacity:.22}}</style><rect width="100%" height="100%" fill="#f8fafc"/>'
    title=f'<text x="40" y="43" font-family="Meiryo,sans-serif" font-size="27">{escape(model.get("name","LAN"))}</text><text x="40" y="76" font-family="Meiryo,sans-serif" font-size="14">{escape(model.get("scope",""))}</text><text x="40" y="106" font-family="Meiryo,sans-serif" font-size="13">YAMLから自動生成 / 機器ごとに集約し、ポート・インターフェース単位の接続を表示</text>'
    return header+title+'\n'+'\n'.join(svg)+'</svg>\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('-o', '--output', type=Path)
    parser.add_argument('--watch', action='store_true', help='regenerate on input changes; Ctrl+C to stop')
    args = parser.parse_args()
    def generate_once():
        try:
            output = args.output or args.input.with_suffix('.svg')
            if output.resolve() == args.input.resolve():
                raise ModelError('output must differ from input YAML')
            model = load_model(args.input.read_text(encoding='utf-8-sig'))
            drawing = render(model)
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
