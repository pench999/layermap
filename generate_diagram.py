"""Render the lan-example/v1 YAML model to a self-contained SVG.

Requires Python 3.10+ and PyYAML. No external drawing service is used.
"""
import argparse
import html
import sys
import time
from pathlib import Path

import yaml
from network_model import ModelError, validate, load_model


def render(model, layers=None, show_bindings=True):
    ix = validate(model)
    layers = tuple(layers) if layers is not None else ('l3', 'l2', 'l1')
    if not layers or len(set(layers)) != len(layers) or any(l not in ('l1', 'l2', 'l3') for l in layers):
        raise ModelError('表示するレイヤーはl1・l2・l3から選択してください')
    devices = list(ix['devices'])
    # Each device has a column; interfaces are real nodes, never inferred from names.
    col = 340
    width = max(1450, 160 + col * len(devices))
    xs = {d: 190 + col * i for i, d in enumerate(devices)}
    svg = []

    def text(x, y, value, size=14, color='#23344d'):
        svg.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}">{html.escape(str(value))}</text>')

    def rect(x, y, w, h, fill='white', stroke='#a8b6c9'):
        svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" fill="{fill}" stroke="{stroke}"/>')

    def line(x1, y1, x2, y2, color='#64748b', dashed=False):
        dash = ' stroke-dasharray="6 4"' if dashed else ''
        svg.append(f'<path d="M{x1},{y1} L{x2},{y2}" fill="none" stroke="{color}" stroke-width="2"{dash}/>')

    palettes = ['#1676b5', '#b56316', '#18856c', '#af3982', '#5e56ba']
    colors = {v: palettes[i % len(palettes)] for i, v in enumerate(ix['l2.vlans'])}
    nodes = {}
    y = 150
    sections = {}
    for layer, group, heading, fill in [
        ('l3', 'l3.interfaces', 'L3 / IPインターフェース・サブネット', '#eaf3fc'),
        ('l2', 'l2.interfaces', 'L2 / VLAN・ブリッジ', '#edf6ef'),
        ('l1', 'l1.ports', 'L1 / 物理ポート・ケーブル', '#f0eff7')]:
        if layer not in layers:
            continue
        svg.append(f'<g data-layer="{layer}">')
        items = ix[group]
        rows = max([sum(i['device'] == d for i in items.values()) for d in devices] + [1])
        buses = (len(ix['l3.subnets']) if layer == 'l3' else
                 len(ix['l2.vlans']) + len(ix['l2.bridges']) if layer == 'l2' else
                 len(ix['l1.links']))
        node_top = y + 80
        bus_top = node_top + rows * 65 + 25
        end = bus_top + max(1, buses) * 45 + 25
        sections[layer] = (y, end)
        rect(20, y, width - 40, end-y, fill, fill)
        text(40, y+30, heading, 22)
        for device in devices:
            x = xs[device]
            text(x-140, y+57, ix['devices'][device].get('name', device), 15)
            for row, item in enumerate(i for i in items.values() if i['device'] == device):
                ny = node_top + row * 65
                nodes[(layer, item['id'])] = (x, ny, ny+48)
                svg.append(f'<g data-device="{html.escape(device, quote=True)}" data-element-id="{html.escape(item["id"], quote=True)}" tabindex="0" role="button" aria-label="{html.escape(item["id"], quote=True)}">')
                rect(x-145, ny, 290, 48)
                text(x-135, ny+19, item['id'])
                detail = (item['address'] if layer == 'l3' else
                          'access / '+item['untagged_vlan'] if layer == 'l2' and item['mode']=='access' else
                          'trunk / '+', '.join(item['tagged_vlans']) if layer == 'l2' else
                          item.get('name', item['id'].split('.')[-1]))
                text(x-135, ny+38, detail, 12)
                svg.append('</g>')
        # Lower buses are relationship nodes: membership is not a direct cable.
        relations = []
        if layer == 'l3':
            for subnet in ix['l3.subnets'].values():
                relations.append((subnet['id']+' / '+subnet['cidr'],
                                  [i['id'] for i in items.values() if i['subnet']==subnet['id']], '#1676b5'))
        elif layer == 'l2':
            for vlan in ix['l2.vlans'].values():
                members = [i['id'] for i in items.values() if vlan['id'] in
                           ([i['untagged_vlan']] if i['mode']=='access' else i['tagged_vlans'])]
                relations.append((f"{vlan['id']} / tag {vlan['tag']} / {vlan.get('label', '')}", members, colors[vlan['id']]))
            for bridge in ix['l2.bridges'].values():
                relations.append((bridge['id']+' / VLAN別に転送', bridge['members'], '#48794b'))
        else:
            for link in ix['l1.links'].values():
                relations.append((f"{link['id']} / {link.get('medium','')} / {link.get('speed','')}", link['endpoints'], '#42556d'))
        for row, (label, members, color) in enumerate(relations):
            by = bus_top + row*45
            # Offset endpoints so multiple interfaces in one column remain visible.
            positions = []
            for j, member in enumerate(members):
                x, top, bottom = nodes[(layer, member)]
                px = x + 150 + (j % 4)*5
                # Route beside the column so edges do not cross other node labels.
                line(x+145, top+24, px, top+24, color)
                line(px, top+24, px, by, color)
                positions.append(px)
                svg.append(f'<circle cx="{px}" cy="{by}" r="3" fill="{color}"/>')
            if positions:
                line(min(positions)-12, by, max(positions)+12, by, color)
            # Label has a background to stay legible over membership lines.
            rect(35, by-21, 280, 20, fill, fill)
            text(40, by-6, label, 12, color)
        gap_rows = max([sum(i['device'] == d for i in items.values()) for d in devices] + [1])
        svg.append('</g>')
        y = end + (max(125, 65 + gap_rows * 15) if show_bindings else 35)
    # Dashed curves in dedicated gutters show every cross-layer binding.
    for upper, lower, key, akey, bkey in [
        ('l3','l2','l3_to_l2','l3_interface','l2_interface'),
        ('l2','l1','l2_to_l1','l2_interface','physical_port')]:
        if not show_bindings or upper not in sections or lower not in sections:
            continue
        svg.append('<g data-binding="'+key+'">')
        gutter_top = sections[upper][1]
        for j, binding in enumerate(model['bindings'][key]):
            a, b = binding[akey], binding[bkey]
            x1 = nodes[(upper,a)][0]
            x2 = nodes[(lower,b)][0]
            # Full mapping is readable in each device column's gap; curves connect rows.
            offset = (j % 5 - 2)*14
            start = nodes[(upper,a)][2]
            finish = nodes[(lower,b)][1]
            svg.append(f'<path d="M{x1+140},{start-8} C{x1+165+offset},{start} {x2+165+offset},{finish} {x2+140},{finish+8}" fill="none" stroke="#8665a6" stroke-width="1.5" stroke-dasharray="5 5"/>')
        text(40, gutter_top+24, '層間対応（紫破線） / '+key, 14, '#765194')
        for device in devices:
            bindings = [b for b in model['bindings'][key] if ix[f'{upper}.interfaces'][b[akey]]['device']==device]
            for row, binding in enumerate(bindings):
                # Grow gap dynamically below, based on interface count.
                suffix = ' / '+binding['vlan'] if 'vlan' in binding else ''
                text(xs[device]-140, gutter_top+45+row*15,
                     binding[akey]+' → '+binding[bkey]+suffix, 10, '#765194')
        svg.append('</g>')
    y = max(bottom for _, bottom in sections.values()) + 35
    if 'l1' in layers:
        text(40, y, 'L1 機器台帳 / 現在の状態', 22)
        heights = []
        for device in devices:
            d = ix['devices'][device]
            loc = d.get('location', {})
            lines = [d.get('name', device)+' / '+device,
                     'メーカー：'+str(d.get('manufacturer', '未設定')),
                     '型番：'+str(d.get('model', '未設定')),
                     'S/N：'+str(d.get('serial_number', '未設定'))]
            loclabels = {'site':'拠点','room':'室','position':'位置','rack':'ラック','rack_unit':'U'}
            lines += [loclabels.get(k,k)+'：'+str(v) for k,v in loc.items()]
            h = 30+24*len(lines)
            heights.append(h)
            svg.append(f'<g data-device="{html.escape(device, quote=True)}" tabindex="0" role="button" aria-label="{html.escape(device, quote=True)}">')
            rect(xs[device]-145, y+15, 290, h)
            for row, label in enumerate(lines):
                text(xs[device]-135, y+40+24*row, label, 13)
            svg.append('</g>')
        y += max(heights, default=0)+75
    if 'l3' in layers:
        text(40,y,'L3経路（矢印は次ホップ指定。通信許可を意味しません）',20)
        y += 28
        for route in model['l3'].get('routes', []):
            text(40,y,f"{route['device']} / {route['interface']} : {route['destination']} → {route['next_hop']}")
            y += 24
    for note in model.get('notes', []):
        text(40,y+15,'注：'+note,13)
        y += 24
    text(40,y+25,'実線：各層の関係（L3＝サブネット所属、L2＝VLAN所属・ブリッジ、L1＝ケーブル） / 紫破線：層間対応',13)
    height = y+55
    header = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><style>text{{font-family:"Yu Gothic",Meiryo,sans-serif}}</style><rect width="100%" height="100%" fill="#f8fafc"/>'
    title = f'<text x="40" y="45" font-family="Meiryo,sans-serif" font-size="28">{html.escape(model.get("name", "LAN"))}</text><text x="40" y="78" font-family="Meiryo,sans-serif" font-size="15">{html.escape(model.get("scope", ""))}</text><text x="40" y="108" font-family="Meiryo,sans-serif" font-size="13">YAMLから自動生成 / lan-example/v1 / インターフェースごとに接続と層間対応を表示</text>'
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
