"""Logical site-to-site overlay; separate-file import never changes source files."""
import ipaddress
import difflib
import yaml
from pydantic import Field, ValidationError
from network_model import Record, VpnConnection, ModelError, MAX_YAML_BYTES, BoundedLoader, guard_yaml, load_model, model_path
from typing import Literal

class VpnDocument(Record):
    schema_version: Literal['layermap-vpn/v1'] = Field(alias='schema')
    vpn_connections: list[VpnConnection] = Field(min_length=1, max_length=128)

class VpnRequest(Record):
    yaml_text: str = Field(max_length=MAX_YAML_BYTES)
    connections_yaml: str = Field(max_length=MAX_YAML_BYTES)

def vpn_members(vpn, ix):
    subnets={s for e in vpn['endpoints'] for s in e['subnets']}
    return [i['id'] for i in ix['l3.interfaces'].values() if i['subnet'] in subnets]

def validate_vpns(data, ix):
    tunnels=set(); addresses={}; tunnel_networks=[]
    members_by_subnet={}
    for iface in ix['l3.interfaces'].values():members_by_subnet.setdefault(iface['subnet'],[]).append(iface)
    for iface in ix['l3.interfaces'].values():
        addresses.setdefault(str(ipaddress.ip_interface(iface['address']).ip),set()).add(iface['device'])
    for n,vpn in enumerate(data['vpn_connections']):
        p=f'vpn_connections[{n}]';ends=vpn['endpoints']
        if ends[0]['site']==ends[1]['site'] or ends[0]['device']==ends[1]['device']:
            raise ModelError('VPNの両端は異なる拠点・機器にしてください',p+'.endpoints')
        networks=[];tunnel_ips=[]
        for j,e in enumerate(ends):
            ep=p+f'.endpoints[{j}]'
            if e['device'] not in ix['devices']:raise ModelError('VPN終端機器が見つかりません: '+e['device'],ep+'.device')
            d=ix['devices'][e['device']]
            if str(d.get('location',{}).get('site',''))!=e['site']:
                raise ModelError('VPN終端機器のlocation.siteとsiteが一致しません',ep+'.site')
            if len(set(e['subnets']))!=len(e['subnets']):raise ModelError('対象サブネットが重複しています',ep+'.subnets')
            local=[]
            for sid in e['subnets']:
                if sid not in ix['l3.subnets']:raise ModelError('対象サブネットが見つかりません: '+sid,ep+'.subnets')
                members=members_by_subnet.get(sid,[])
                if not members or any(str(ix['devices'][i['device']].get('location',{}).get('site',''))!=e['site'] for i in members):
                    raise ModelError('対象サブネットは指定拠点のL3インターフェースだけに所属させてください: '+sid,ep+'.subnets')
                local.append(ipaddress.ip_network(ix['l3.subnets'][sid]['cidr']))
            networks.append(local)
            if vpn['mode']=='route_based':
                if not e.get('tunnel_interface'):raise ModelError('ルート型にはtunnel_interfaceが必要です',ep+'.tunnel_interface')
                identity=(e['device'],e['tunnel_interface'])
                if identity in tunnels:raise ModelError('同じ機器のトンネルIFが重複しています',ep+'.tunnel_interface')
                if any(i['device']==e['device'] and i['id']==e['tunnel_interface'] for i in ix['l3.interfaces'].values()):
                    raise ModelError('トンネルIF名は既存L3インターフェースIDと分けてください',ep+'.tunnel_interface')
                tunnels.add(identity)
                if e.get('tunnel_address'):
                    try:ip=ipaddress.ip_interface(e['tunnel_address'])
                    except ValueError:raise ModelError('トンネルIP/プレフィックスが不正です',ep+'.tunnel_address') from None
                    if str(ip.ip) in addresses:raise ModelError('トンネルIPが既存IPと重複しています',ep+'.tunnel_address')
                    addresses[str(ip.ip)]={e['device']};tunnel_ips.append(ip)
            elif e.get('tunnel_interface') or e.get('tunnel_address'):
                raise ModelError('ポリシー型にはトンネルIF・トンネルIPを指定しません',ep)
        if {net.version for net in networks[0]}!={net.version for net in networks[1]}:
            raise ModelError('両端の対象サブネットのIPバージョンを揃えてください',p+'.endpoints')
        for a in networks[0]:
            for b in networks[1]:
                if a.version==b.version and a.overlaps(b):
                    raise ModelError('VPN対象アドレスが拠点間で重複しています: '+str(a)+' / '+str(b)+'。NAT・VRFは未対応です',p+'.endpoints')
        if tunnel_ips:
            if len(tunnel_ips)!=2 or tunnel_ips[0].network!=tunnel_ips[1].network or tunnel_ips[0].ip==tunnel_ips[1].ip:
                raise ModelError('トンネルIPは両端に異なるIPを同じサブネットで指定するか、両端とも省略してください',p+'.endpoints')
            if any(tunnel_ips[0].network.version==net.version and tunnel_ips[0].network.overlaps(net) for net in tunnel_networks):raise ModelError('異なるVPNのトンネル用サブネットが重複しています',p+'.endpoints')
            tunnel_networks.append(tunnel_ips[0].network)
            if any(tunnel_ips[0].network.version==ipaddress.ip_network(s['cidr']).version and tunnel_ips[0].network.overlaps(ipaddress.ip_network(s['cidr'])) for s in ix['l3.subnets'].values()):
                raise ModelError('トンネル用サブネットがLANサブネットと重複しています',p+'.endpoints')

def preview_vpn(request):
    from input_support import append_records
    load_model(request.yaml_text)
    if len(request.connections_yaml.encode('utf-8'))>MAX_YAML_BYTES:raise ModelError('VPN定義は2 MiB以下にしてください','connections_yaml')
    try:
        guard_yaml(request.connections_yaml)
        doc=VpnDocument.model_validate(yaml.load(request.connections_yaml,Loader=BoundedLoader)).model_dump(exclude_none=True,by_alias=True)
    except ValidationError as error:
        e=error.errors(include_input=False)[0];raise ModelError(e['msg'],'connections_yaml.'+model_path(e['loc'])) from None
    except (yaml.YAMLError,RecursionError) as error:
        raise ModelError('VPN定義のYAML構文が不正です: '+str(error).splitlines()[0],'connections_yaml') from None
    candidate,changes=append_records(request.yaml_text,{('vpn_connections',):doc['vpn_connections']})
    model=load_model(candidate)
    return dict(yaml_text=candidate,changes=changes,summary=[dict(path='vpn_connections',count=len(doc['vpn_connections']))],diff=''.join(difflib.unified_diff(request.yaml_text.splitlines(keepends=True),candidate.splitlines(keepends=True))),added=len(doc['vpn_connections']),total=len(model['vpn_connections']),
                message='VPNを追加します。元ファイルは変更しません。定義は通信可否・稼働状態の証明ではありません。')
