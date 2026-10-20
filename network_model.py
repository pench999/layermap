"""Shared, bounded YAML model validation for CLI and HTTP requests."""
import ipaddress
from datetime import datetime
import re
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAX_YAML_BYTES = 2 * 1024 * 1024
MAX_DEVICES = 256
MAX_ELEMENTS = 10000
MAX_YAML_NODES = 200000
MAX_YAML_DEPTH = 48
Text = Annotated[str, Field(min_length=1, max_length=200)]
Id = Annotated[str, Field(min_length=1, max_length=100)]


class ModelError(ValueError):
    def __init__(self, message, path='', line=None, column=None):
        super().__init__(message)
        self.path, self.line, self.column = path, line, column


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Device(Record):
    id: Id
    role: Text = 'device'
    label: Text | None = None
    name: Text | None = None
    manufacturer: Text | None = None
    model: Text | None = None
    serial_number: Text | None = None
    groups: list[Id] = Field(default_factory=list, max_length=16)
    location: dict[Text, Text | int] = Field(default_factory=dict, max_length=12)


class Port(Record):
    kind: Literal['wired','wifi'] = 'wired'
    id: Id
    device: Id
    name: Text | None = None
    connector: Text | None = None


class Link(Record):
    id: Id
    endpoints: list[Id] = Field(min_length=2, max_length=2)
    medium: Text | None = None
    speed: Text | None = None


class ConnectionEndpoint(Record):
    port: Id | None = None
    device: Id | None = None
    unknown: Literal[True] | None = None


class Connection(Record):
    id: Id
    kind: Literal['wired','wifi']
    status: Literal['confirmed','port_unknown','peer_unknown']
    endpoints: list[ConnectionEndpoint] = Field(min_length=2, max_length=2)
    ssid: Text | None = None
    observed_at: Text | None = None
    note: Text | None = None
    medium: Text | None = None
    speed: Text | None = None


class L1(Record):
    ports: list[Port]
    links: list[Link]
    connections: list[Connection] = Field(default_factory=list)


class Vlan(Record):
    id: Id
    tag: int = Field(ge=1, le=4094)
    label: Text | None = None


class L2Interface(Record):
    id: Id
    device: Id
    mode: Literal['access', 'trunk', 'svi']
    vlan: Id | None = None
    untagged_vlan: Id | None = None
    tagged_vlans: list[Id] = Field(default_factory=list, max_length=64)


class Bridge(Record):
    id: Id
    device: Id
    members: list[Id] = Field(max_length=128)


class L2(Record):
    vlans: list[Vlan]
    interfaces: list[L2Interface]
    bridges: list[Bridge]


class Subnet(Record):
    id: Id
    cidr: Text


class L3Interface(Record):
    id: Id
    device: Id
    address: Text
    subnet: Id


class Route(Record):
    device: Id
    destination: Text
    next_hop: Text
    interface: Id


class L3(Record):
    subnets: list[Subnet]
    interfaces: list[L3Interface]
    routes: list[Route] = Field(default_factory=list)


class L2Binding(Record):
    l2_interface: Id
    physical_port: Id


class L3Binding(Record):
    l3_interface: Id
    l2_interface: Id
    vlan: Id


class Bindings(Record):
    l2_to_l1: list[L2Binding]
    l3_to_l2: list[L3Binding]


class VpnEndpoint(Record):
    site: Id
    device: Id
    subnets: list[Id] = Field(min_length=1, max_length=64)
    tunnel_interface: Text | None = None
    tunnel_address: Text | None = None


class VpnConnection(Record):
    id: Id
    name: Text
    technology: Literal['ipsec'] = 'ipsec'
    mode: Literal['route_based', 'policy_based']
    endpoints: list[VpnEndpoint] = Field(min_length=2, max_length=2)


class Network(Record):
    schema_version: Literal['lan-example/v1'] = Field(alias='schema')
    name: Text = 'LAN'
    scope: Text = '社内LAN'
    devices: list[Device] = Field(max_length=MAX_DEVICES)
    l1: L1
    l2: L2
    l3: L3
    vpn_connections: list[VpnConnection] = Field(default_factory=list, max_length=128)
    bindings: Bindings
    notes: list[Annotated[str, Field(max_length=500)]] = Field(default_factory=list, max_length=20)


def model_path(parts):
    result = ''
    for part in parts:
        result += f'[{part}]' if isinstance(part, int) else ('.' if result else '') + str(part)
    return result


def validate(data):
    try:
        data = Network.model_validate(data).model_dump(exclude_none=True, by_alias=True)
    except ValidationError as exc:
        error = exc.errors(include_input=False)[0]
        raise ModelError(error['msg'], model_path(error['loc'])) from None
    groups = {'devices': data['devices'], 'vpn_connections': data['vpn_connections']}
    for layer, names in [('l1', ['ports', 'links', 'connections']), ('l2', ['vlans', 'interfaces', 'bridges']), ('l3', ['subnets', 'interfaces'])]:
        groups.update({f'{layer}.{n}': data[layer][n] for n in names})
    count = sum(len(v) for v in groups.values()) + len(data['l3']['routes']) + sum(len(v) for v in data['bindings'].values())
    if count > MAX_ELEMENTS:
        raise ModelError(f'要素数は合計{MAX_ELEMENTS}以下にしてください')
    ix, positions = {}, {}
    for group, items in groups.items():
        ix[group] = {}
        for n, item in enumerate(items):
            p = f'{group}[{n}]'
            if item['id'] in ix[group]:
                raise ModelError('IDが重複しています', p+'.id')
            ix[group][item['id']] = item
            positions[(group, item['id'])] = p

    def ref(value, group, p):
        if value not in ix[group]:
            raise ModelError(f'参照先 {value!r} が {group} にありません', p)
        return ix[group][value]

    for group in ['l1.ports', 'l2.interfaces', 'l2.bridges', 'l3.interfaces']:
        for item in groups[group]:
            ref(item['device'], 'devices', positions[(group,item['id'])]+'.device')
    used_ports = set()
    for n, link in enumerate(data['l1']['links']):
        for j, port in enumerate(link['endpoints']):
            p = f'l1.links[{n}].endpoints[{j}]'
            ref(port, 'l1.ports', p)
            if ix['l1.ports'][port]['kind']!='wired':
                raise ModelError('l1.linksは有線用です。Wi-Fiはl1.connectionsに定義してください',p)
            if port in used_ports:
                raise ModelError('同じ物理ポートを複数のケーブル端点には指定できません', p)
            used_ports.add(port)
    for n, connection in enumerate(data['l1']['connections']):
        p=f'l1.connections[{n}]'
        if connection['id'] in ix['l1.links']:
            raise ModelError('接続IDがl1.linksと重複しています',p+'.id')
        forms=[]
        for j, endpoint in enumerate(connection['endpoints']):
            ep=p+f'.endpoints[{j}]'
            if len(endpoint)!=1:
                raise ModelError('端点はport・device・unknownのどれか一つだけを指定してください',ep)
            form=next(iter(endpoint));forms.append(form)
            if form=='port':
                port=ref(endpoint['port'],'l1.ports',ep+'.port')
                if port['kind']!=connection['kind']:
                    raise ModelError('接続方式とポートのkindが一致しません',ep+'.port')
                if connection['kind']=='wired':
                    if endpoint['port'] in used_ports:
                        raise ModelError('同じ物理ポートを複数の有線接続端点には指定できません',ep+'.port')
                    used_ports.add(endpoint['port'])
            elif form=='device':ref(endpoint['device'],'devices',ep+'.device')
        expected={'confirmed':['port','port'],'port_unknown':['device','port'],'peer_unknown':['port','unknown']}[connection['status']]
        if sorted(forms)!=expected:
            raise ModelError('statusと端点の確認範囲が一致しません（confirmed=port+port、port_unknown=port+device、peer_unknown=port+unknown）',p+'.status')
        if forms==['port','port'] and connection['endpoints'][0]['port']==connection['endpoints'][1]['port']:
            raise ModelError('同じポート自身へは接続できません',p+'.endpoints')
        if connection['kind']=='wired' and connection.get('ssid'):
            raise ModelError('SSIDはWi-Fi接続だけに指定できます',p+'.ssid')
        if connection.get('observed_at'):
            try:
                stamp=datetime.fromisoformat(connection['observed_at'].replace('Z','+00:00'))
                if stamp.tzinfo is None:raise ValueError()
            except ValueError:
                raise ModelError('確認日時はタイムゾーン付きISO 8601形式にしてください',p+'.observed_at') from None
    for n, item in enumerate(data['l2']['interfaces']):
        p = f'l2.interfaces[{n}]'
        if item['mode'] == 'svi':
            if not item.get('vlan') or item.get('untagged_vlan') or item['tagged_vlans']:
                raise ModelError('SVIにはvlanのみを指定してください',p)
            ref(item['vlan'],'l2.vlans',p+'.vlan')
        elif item.get('vlan'):
            raise ModelError('vlanはSVI専用です。access/trunkには従来のVLAN項目を指定してください',p+'.vlan')
        elif item['mode'] == 'access':
            if not item.get('untagged_vlan') or item['tagged_vlans']:
                raise ModelError('accessにはuntagged_vlanのみを指定してください', p)
            ref(item['untagged_vlan'], 'l2.vlans', p+'.untagged_vlan')
        else:
            if not item['tagged_vlans'] or item.get('untagged_vlan'):
                raise ModelError('trunkにはtagged_vlansのみを指定してください', p)
            for j, v in enumerate(item['tagged_vlans']):
                ref(v, 'l2.vlans', p+f'.tagged_vlans[{j}]')
    bridge_memberships={}
    for n, bridge in enumerate(data['l2']['bridges']):
        for j, member in enumerate(bridge['members']):
            p = f'l2.bridges[{n}].members[{j}]'
            if ref(member, 'l2.interfaces', p)['device'] != bridge['device']:
                raise ModelError('ブリッジのメンバーは同じ機器に所属する必要があります', p)
            bridge_memberships.setdefault(member,[]).append(bridge)
    svi_domains=set()
    for item in data['l2']['interfaces']:
        if item['mode']!='svi':continue
        p=positions[('l2.interfaces',item['id'])]
        memberships=bridge_memberships.get(item['id'],[])
        if len(memberships)!=1:
            raise ModelError('SVIは同じ機器のbridgeに一度だけ所属させてください',p)
        domain=(memberships[0]['id'],item['vlan'])
        if domain in svi_domains:raise ModelError('同じbridge・VLANのSVIが重複しています',p)
        svi_domains.add(domain)
    nets = {}
    for n, subnet in enumerate(data['l3']['subnets']):
        try:
            nets[subnet['id']] = ipaddress.ip_network(subnet['cidr'])
        except ValueError:
            raise ModelError('正しいネットワークアドレス/プレフィックスを指定してください', f'l3.subnets[{n}].cidr') from None
    for n, interface in enumerate(data['l3']['interfaces']):
        p = f'l3.interfaces[{n}]'
        ref(interface['subnet'], 'l3.subnets', p+'.subnet')
        try:
            network = ipaddress.ip_interface(interface['address']).network
        except ValueError:
            raise ModelError('正しいIPアドレス/プレフィックスを指定してください', p+'.address') from None
        if network != nets[interface['subnet']]:
            raise ModelError('IPのネットワークと所属サブネットが一致しません', p+'.address')
    bound2, bound3 = set(), set()
    for n, b in enumerate(data['bindings']['l2_to_l1']):
        p = f'bindings.l2_to_l1[{n}]'
        a = ref(b['l2_interface'], 'l2.interfaces', p+'.l2_interface')
        if a['mode']=='svi':raise ModelError('SVIを物理ポートへ対応付けることはできません',p+'.l2_interface')
        port = ref(b['physical_port'], 'l1.ports', p+'.physical_port')
        if b['l2_interface'] in bound2 or a['device'] != port['device']:
            raise ModelError('L2対応が重複しているか、物理ポートの機器が異なります', p)
        bound2.add(b['l2_interface'])
    for n, b in enumerate(data['bindings']['l3_to_l2']):
        p = f'bindings.l3_to_l2[{n}]'
        a = ref(b['l3_interface'], 'l3.interfaces', p+'.l3_interface')
        lower = ref(b['l2_interface'], 'l2.interfaces', p+'.l2_interface')
        ref(b['vlan'], 'l2.vlans', p+'.vlan')
        allowed = interface_vlans(lower)
        if b['vlan'] not in allowed:
            raise ModelError('対応先のL2インターフェースでこのVLANは使用されていません', p+'.vlan')
        if b['l3_interface'] in bound3 or a['device'] != lower['device']:
            raise ModelError('L3対応が重複しているか、L2インターフェースの機器が異なります', p)
        bound3.add(b['l3_interface'])
    for group, bound in [('l2.interfaces',bound2),('l3.interfaces',bound3)]:
        for key in ix[group].keys()-bound:
            if group=='l2.interfaces' and ix[group][key]['mode']=='svi':continue
            raise ModelError('下位レイヤーへの対応が必要です', positions[(group,key)])
    for n, r in enumerate(data['l3']['routes']):
        p = f'l3.routes[{n}]'
        ref(r['device'], 'devices', p+'.device')
        iface = ref(r['interface'], 'l3.interfaces', p+'.interface')
        try:
            dest = ipaddress.ip_network(r['destination'])
            hop = ipaddress.ip_address(r['next_hop'])
        except ValueError:
            raise ModelError('経路のアドレスが不正です', p) from None
        if iface['device'] != r['device'] or hop.version != dest.version or hop not in ipaddress.ip_interface(iface['address']).network:
            raise ModelError('経路の機器または次ホップがインターフェースと一致しません', p)
    from vpn_model import validate_vpns
    validate_vpns(data, ix)
    return ix


BaseLoader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


class BoundedLoader(BaseLoader):
    def __init__(self, stream):
        super().__init__(stream)
        self.node_count = 0

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise yaml.YAMLError('YAMLのエイリアスは使用できません')
        self.node_count += 1
        if self.node_count > MAX_YAML_NODES:
            raise yaml.YAMLError('YAMLの構造が大きすぎます')
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        keys = set()
        for key, _ in node.value:
            if not isinstance(key, yaml.ScalarNode) or key.value in keys:
                raise yaml.YAMLError('重複キーまたは非スカラーのキーは使用できません')
            keys.add(key.value)
        return super().construct_mapping(node, deep)


def guard_yaml(source):
    # C loaders do not call Python compose_node. Stream the events first so
    # alias/node/depth limits apply with either the C or pure-Python loader.
    count = depth = 0
    for event in yaml.parse(source, Loader=BaseLoader):
        if isinstance(event, yaml.AliasEvent):
            raise yaml.YAMLError('YAMLのエイリアスは使用できません')
        if isinstance(event, (yaml.ScalarEvent, yaml.MappingStartEvent, yaml.SequenceStartEvent)):
            count += 1
            if count > MAX_YAML_NODES:
                raise yaml.YAMLError('YAMLの構造が大きすぎます')
        if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
            depth += 1
            if depth > MAX_YAML_DEPTH:
                raise yaml.YAMLError('YAMLの入れ子が深すぎます')
        elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
            depth -= 1


def locate(source, p):
    guard_yaml(source)
    node = yaml.compose(source, Loader=BoundedLoader)
    for key, number in re.findall(r'([^.\[\]]+)|\[(\d+)\]', p):
        if number and isinstance(node, yaml.SequenceNode):
            node = node.value[int(number)]
        elif key and isinstance(node, yaml.MappingNode):
            node = next((v for k,v in node.value if k.value == key), node)
        else:
            break
    return (node.start_mark.line+1, node.start_mark.column+1) if node else (None,None)


def load_model(source, with_index=False):
    if len(source.encode('utf-8')) > MAX_YAML_BYTES:
        raise ModelError(f'YAMLは{MAX_YAML_BYTES // 1024} KiB以下にしてください')
    try:
        guard_yaml(source)
        model = yaml.load(source, Loader=BoundedLoader)
        ix = validate(model)
        return (model, ix) if with_index else model
    except ModelError as exc:
        if exc.path:
            exc.line, exc.column = locate(source, exc.path)
        raise
    except (yaml.YAMLError, RecursionError) as exc:
        mark = getattr(exc, 'problem_mark', None)
        raise ModelError('YAML構文: '+str(getattr(exc, 'problem', None) or str(exc).splitlines()[0]),
                         line=mark.line+1 if mark else None, column=mark.column+1 if mark else None) from None


def all_l1_connections(ix):
    legacy=[dict(link,kind='wired',status='confirmed',endpoints=[{'port':p} for p in link['endpoints']]) for link in ix['l1.links'].values()]
    return legacy+list(ix['l1.connections'].values())


def endpoint_owner(endpoint,ix):
    return ix['l1.ports'][endpoint['port']]['device'] if 'port' in endpoint else endpoint.get('device')


def endpoint_label(endpoint):
    return endpoint['port'] if 'port' in endpoint else endpoint['device']+'（ポート／無線IF未確認）' if 'device' in endpoint else '接続先未確認'


def connection_label(connection):
    status={'confirmed':'両端確認済み','port_unknown':'ポート／無線IF未確認','peer_unknown':'接続先未確認'}[connection['status']]
    return ('Wi-Fi' if connection['kind']=='wifi' else '有線')+' / '+status+' / '+' ↔ '.join(endpoint_label(e) for e in connection['endpoints'])+(' / SSID: '+connection['ssid'] if connection.get('ssid') else '')+(' / 確認: '+connection['observed_at'] if connection.get('observed_at') else '')+(' / '+connection['medium'] if connection.get('medium') else '')+(' / '+connection['speed'] if connection.get('speed') else '')+(' / '+connection['note'] if connection.get('note') else '')


def interface_vlans(item):
    """Explicit VLAN membership, including a port-independent SVI endpoint."""
    return [item['vlan']] if item['mode']=='svi' else [item['untagged_vlan']] if item['mode']=='access' else item.get('tagged_vlans',[])
