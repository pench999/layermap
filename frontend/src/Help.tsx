import {useEffect,useRef} from 'react';
import {type Limits,sizeLabel} from './scope';
export type Sample = {id:string;title:string;description:string;filename:string};
type Props = {limits:Limits;samples:Sample[];loading:boolean;error:string;onClose:()=>void;onLoadSample:(id:string)=>Promise<boolean>};
const fields:[string,string][] = [
 ['schema','データ形式。現在は lan-example/v1 固定です。'],
 ['name / scope','図面のタイトル / 図面で扱う範囲の説明。'],
 ['devices','全レイヤーで共通して参照する機器台帳。'],
 ['l1.ports','物理ポート。id＝固定ID、device＝所属機器ID、name＝実際のポート名、connector＝コネクター種別（任意）。'],
 ['l1.links','ケーブル。id＝固定ID、endpoints＝両端の物理ポートID、medium＝媒体、speed＝速度。'],
 ['l2.vlans','id＝VLANの内部ID、tag＝実際のVLAN番号（整数1〜4094）、label＝名称。'],
 ['l2.interfaces','id＝L2インターフェースID、device＝所属機器、mode＝access または trunk。accessはuntagged_vlan、trunkはtagged_vlansを指定します。'],
 ['l2.bridges','スイッチ内の転送関係。id＝固定ID、device＝所属機器ID、members＝同じ機器に所属するL2インターフェースIDの一覧。VLAN別に転送します。'],
 ['l3.subnets','id＝サブネットID、cidr＝ネットワークアドレス/プレフィックス。例：192.168.10.0/24。'],
 ['l3.interfaces','id＝IPインターフェースID、device＝所属機器、address＝IP/プレフィックス、subnet＝所属サブネットID。'],
 ['l3.routes','device＝経路を持つ機器、destination＝宛先、next_hop＝次ホップIP、interface＝使用するL3インターフェースID。0.0.0.0/0はIPv4のデフォルト経路です。'],
 ['bindings.l2_to_l1','l2_interfaceが、どのphysical_portを使うか。'],
 ['bindings.l3_to_l2','l3_interfaceが、どのl2_interfaceの、どのvlan（内部ID）に対応するか。'],
 ['notes','図面に表示する補足事項。文字列のリストです。'],
];
const deviceFields:[string,string][] = [
 ['id','他の項目から参照する固定ID。機器同士で重複させません。'],
 ['role','endpoint、l2-switch、internet-gatewayなどの役割。指定しただけではポートや接続は作られません。'],
 ['label / name','補足名称 / 運用上の機器名。現在の図では主にnameを表示します。'],
 ['manufacturer / model','メーカー / 型番。'],
 ['serial_number','シリアルNo。数字だけでも引用符で囲み、文字列にします。'],
 ['groups','任意の機器群。例：groups: [ネットワーク機器, 1F]。複数の群に所属でき、画面の絞り込みに使います。'],
 ['location','設置場所。site＝拠点、room＝部屋、rack＝ラック、rack_unit＝U位置、position＝座席など。値は文字列か整数です。'],
];
function Fields({rows}:{rows:[string,string][]}){return <div className="help-table-wrap"><table className="help-table"><thead><tr><th>項目</th><th>意味</th></tr></thead><tbody>{rows.map(([key,value])=><tr key={key}><td><code>{key}</code></td><td>{value}</td></tr>)}</tbody></table></div>;}
function Code({lines}:{lines:string[]}){return <pre className="help-code"><code>{lines.join(String.fromCharCode(10))}</code></pre>;}
export function Help({limits,samples,loading,error,onClose,onLoadSample}:Props){
 const dialog=useRef<HTMLDialogElement>(null);
 useEffect(()=>{dialog.current?.showModal();},[]);
 const move=(id:string)=>dialog.current?.querySelector('#'+id)?.scrollIntoView({block:'start'});
 const load=async(id:string)=>{if(await onLoadSample(id))dialog.current?.close();};
 return <dialog ref={dialog} className="help-dialog" aria-labelledby="help-title" onClose={onClose} onClick={e=>{const modal=dialog.current;if(modal&&e.target===modal){const r=modal.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)modal.close();}}}>
 <header className="help-header"><div><div className="eyebrow">LAYERMAP GUIDE</div><h2 id="help-title">YAMLの書き方と構成の追加</h2><p>機器・接続・レイヤーの対応を、ひとつずつ。</p></div><button autoFocus className="help-close" aria-label="ヘルプを閉じる" onClick={()=>dialog.current?.close()}>×</button></header>
 <nav className="help-nav" aria-label="ヘルプの目次"><button onClick={()=>move('help-fields')}>項目の意味</button><button onClick={()=>move('help-pc')}>機器を追加</button><button onClick={()=>move('help-vlan')}>VLANを追加</button><button onClick={()=>move('help-scope')}>表示範囲</button><button onClick={()=>move('help-rules')}>入力ルール</button></nav>
 <div className="help-body"><p className="help-lead">まず業務LANへPCを1台追加し、次にそのPCを新しいVLANへ移すと、各項目の関係を確認できます。図面への入力は実機の設定を変更しません。</p>
 <section className="help-samples" aria-label="ヘルプのサンプル"><h3>完成例を読み込んで試す</h3><p>サンプルは編集中のYAMLを置き換えます。未保存の編集がある場合は確認を表示します。</p><div className="help-sample-grid">{samples.map(s=><article key={s.id}><span className="sample-tag">{s.id==='base'?'START':s.id==='add-pc'?'STEP 01':'STEP 02'}</span><h4>{s.title}</h4><p>{s.description}</p><button disabled={loading} onClick={()=>load(s.id)}>{s.title}を読み込む</button></article>)}</div>{error&&<p className="sample-error" role="alert">{error}</p>}</section>
 <section id="help-fields"><div className="help-section-number">01 / REFERENCE</div><h3>各項目の意味</h3><p>機器・物理ポート・L2インターフェース・IPを個別に定義し、<code>bindings</code>で対応付けます。</p><Fields rows={fields}/><h4>機器台帳のフィールド</h4><Fields rows={deviceFields}/><h4>accessとtrunkの記述</h4><Code lines={['# タグなしでVLAN 10に所属','mode: access','untagged_vlan: vlan-office','','# VLAN 10と20をタグ付きで通す','mode: trunk','tagged_vlans: [vlan-office, vlan-guest]']}/><div className="help-callout"><strong>内部IDとVLAN番号は別のものです。</strong><p><code>vlan-office</code>は内部ID、<code>10</code>は実際のVLAN番号です。参照には内部IDを使います。<code>pc-c.eth0</code>の「.」も命名上の区切りであり、名前から所属は推測しません。</p></div></section>
 <section id="help-pc"><div className="help-section-number">02 / ADD A DEVICE</div><h3>既存のVLAN 10へPCを追加する</h3><p><code>HQ-PC-03 → SW01のポート3</code>を追加します。IPは<code>192.168.10.30/24</code>、ゲートウェイは<code>192.168.10.1</code>です。</p><div className="help-callout"><strong>断片は既存のリストへ追加してください。</strong><p>下のコードにはリストの見出しを含めていません。<code>l1:</code>などの見出しを重複して作るとエラーになります。完成例は「機器追加版」から読み込めます。</p></div>
 <h4>① devicesに機器を追加</h4><Code lines={['- id: pc-c','  role: endpoint','  name: HQ-PC-03','  manufacturer: Example Computing','  model: EC-Desktop-100',"  serial_number: 'DEMO-PC-0003'",'  location:','    site: 本社','    room: 執務室','    position: 座席A03']}/>
 <h4>② l1.portsに両端の物理ポートを追加</h4><Code lines={['- {id: pc-c.eth0, device: pc-c, name: Ethernet0}','- {id: sw01.p3, device: sw01, name: GigabitEthernet1/0/3}']}/><p><code>l1.links</code>へケーブルを追加します。</p><Code lines={['- id: cable-c','  endpoints: [pc-c.eth0, sw01.p3]','  medium: copper','  speed: 1Gbps']}/>
 <h4>③ l2.interfacesにVLAN所属を追加</h4><Code lines={['- {id: pc-c.l2, device: pc-c, mode: access, untagged_vlan: vlan-office}','- {id: sw01.access3, device: sw01, mode: access, untagged_vlan: vlan-office}']}/><p>既存の<code>sw01.bridge</code>の<code>members</code>へ<code>sw01.access3</code>を追加します。</p><Code lines={['members: [sw01.access1, sw01.access2, sw01.trunk, sw01.access3]']}/>
 <h4>④ l3.interfacesにIPを追加</h4><Code lines={['- id: pc-c.ip','  device: pc-c','  address: 192.168.10.30/24','  subnet: net-office']}/><p><code>l3.routes</code>へデフォルト経路を追加します。</p><Code lines={['- device: pc-c','  destination: 0.0.0.0/0','  next_hop: 192.168.10.1','  interface: pc-c.ip']}/>
 <h4>⑤ bindingsで層間を対応付ける</h4><p><code>bindings.l2_to_l1</code>へ追加します。</p><Code lines={['- {l2_interface: pc-c.l2, physical_port: pc-c.eth0}','- {l2_interface: sw01.access3, physical_port: sw01.p3}']}/><p><code>bindings.l3_to_l2</code>へ追加します。</p><Code lines={['- {l3_interface: pc-c.ip, l2_interface: pc-c.l2, vlan: vlan-office}']}/><p className="help-result">完了時：5機器・4ケーブル・2 VLAN</p></section>
 <section id="help-vlan"><div className="help-section-number">03 / ADD A VLAN</div><h3>新しいVLAN 30を追加する</h3><p>「機器追加版」を基に、追加したPCを検証用LANへ移します。</p><Fields rows={[
 ['l2.vlans','id: vlan-lab、tag: 30、label: 検証LANを追加。'],
 ['l2.interfaces','pc-c.l2とsw01.access3のuntagged_vlanをvlan-labへ変更。'],
 ['既存トランク','sw01.trunkとgw01.trunkの両方のtagged_vlansにvlan-labを追加。'],
 ['l3.subnets','id: net-lab、cidr: 192.168.30.0/24を追加。'],
 ['PCのL3','pc-c.ipを192.168.30.30/24、subnet: net-labへ変更。'],
 ['GWのL3','id: gw01.v30、device: gw01、address: 192.168.30.1/24、subnet: net-labを追加。'],
 ['PCの経路','pc-cのnext_hopを192.168.30.1へ変更。'],
 ['PCのL3→L2対応','pc-c.ipのvlanをvlan-labへ変更。'],
 ['GWのL3→L2対応','l3_interface: gw01.v30、l2_interface: gw01.trunk、vlan: vlan-labを追加。'],
 ]}/><div className="help-callout"><strong>物理ポート・ケーブルは追加不要です。</strong><p>既存のトランク回線を使用します。完成例は「VLAN追加版」から読み込めます。</p></div><p className="help-result">完了時：5機器・4ケーブル・3 VLAN</p></section>
 <section id="help-scope"><h3>構成全体と表示範囲を分ける</h3><p>保持できるYAMLは{sizeLabel(limits.yaml_bytes)}、機器{limits.devices}台、全要素{limits.elements.toLocaleString()}件までです。ここでの保持はエディター内の構成全体を指し、サーバーへの永続保存は行いません。</p><p>一度に描画できる範囲は{limits.view_devices}台・{limits.view_rows}行・接続／所属{limits.view_connections}件・構成要素{limits.view_elements}件・VLAN／ブリッジ／サブネット{limits.view_groups}件までです。trunkのVLAN所属も1件ずつ数えます。構成全体が有効でも描画上限を超える場合は、表示条件の変更を案内します。</p><ol><li>拠点はdevices.location.site、機器群はdevices.groupsに記述します。</li><li>「表示範囲」で拠点・機器群・機器を選びます。条件はANDで適用されます。</li><li>1台に絞ると「対応関係の起点」でポートやインターフェースを選べます。図の行を選んだ追跡パネルの「この対応だけを表示」からも絞れます。</li><li>対応関係はbindingsのみを双方向にたどります。trunkで共有するポートの分岐も含み、VLAN所属やケーブルの接続先へはたどりません。</li><li>「絞り込みを解除」で元の表示範囲へ戻ります。YAML保存は常に構成全体、SVG出力は現在の表示範囲です。</li></ol><p>範囲外につながるケーブルは線を省略し、一覧で両端を確認できます。同一VLAN・サブネットの範囲外の機器も省略します。入力の検証は表示範囲外も含めて行います。</p><Code lines={['groups: [ネットワーク機器, 1F]','location:','  site: 本社','  room: サーバー室']}/></section>
 <section id="help-rules"><div className="help-section-number">04 / CHECKLIST</div><h3>入力時の確認と保存</h3><ul><li>字下げにはタブではなくスペースを使います。</li><li>IDは各リスト内で重複させず、参照先を対応するリストへ登録します。</li><li>すべてのL2・L3インターフェースに、下位層へのbindingsが必要です。</li><li>IPのプレフィックスと所属サブネットを一致させます。</li><li>スイッチ内の転送に参加するポートはbridges.membersへ追加します。</li><li>同じ物理ポートを複数のケーブル端点に指定できません。</li><li>LAG・VRF・トランクのnative VLANの専用項目は現行版では未対応です。</li><li>YAMLは{sizeLabel(limits.yaml_bytes)}、機器は{limits.devices}台、全要素は{limits.elements.toLocaleString()}件まで。未定義項目・重複キー・エイリアスは拒否します。</li></ul><p>入力途中でエラーが出ても、項目がそろうと図が更新されます。エラー中は最後の正常な図を表示し、SVG出力を無効にします。</p><div className="help-callout"><strong>編集内容は自動保存されません。</strong><p>最後に「YAMLを保存」を押してください。YAMLは描画のためサーバーへ送信されますが、永続保存されません。経路やVLANの記述は、実機の通信可否や許可設定を保証するものではありません。</p></div></section>
 </div></dialog>;
}
