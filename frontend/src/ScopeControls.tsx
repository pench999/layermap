import {emptyScope,sizeLabel,type Scope,type Result,type Limits} from './scope';
import type {Endpoint} from './trace';
type Props={scope:Scope;result:Result|null;limits:Limits;onChange:(s:Scope)=>void;onFocus:(e:Endpoint|null)=>void;pending:boolean};
export function ScopeControls({scope,result,limits,onChange,onFocus,pending}:Props){
 const facet=(kind:'site'|'group',values:string[])=>{
  const current=scope[kind];
  const choices=current!==null&&!values.includes(current)?[current,...values]:values;
  return <label>{kind==='site'?'拠点':'機器群'}<select aria-label={kind==='site'?'表示する拠点':'表示する機器群'} value={JSON.stringify(current)} onChange={e=>onChange({...scope,[kind]:JSON.parse(e.target.value),device_ids:[],trace_root:null})}><option value="null">すべて</option>{choices.map(v=><option key={v} value={JSON.stringify(v)}>{v||'未設定'}{!values.includes(v)?'（現在の構成にありません）':''}</option>)}</select></label>;
 };
 const candidates=result?.devices.filter(d=>(scope.site===null||d.site===scope.site)&&(scope.group===null||(scope.group?d.groups.includes(scope.group):!d.groups.length)))??[];
 const ids=new Set(candidates.map(d=>d.id));
 const missing=scope.device_ids.filter(id=>!ids.has(id));
 const roots=result?.catalog.focus_options??[];
 const rootValue=scope.trace_root?JSON.stringify(scope.trace_root):'';
 const knownRoot=roots.some(r=>r.id===scope.trace_root?.id&&r.layer===scope.trace_root?.layer);
 return <section className="scope-controls" aria-label="表示範囲">
  <div className="scope-title"><strong>表示範囲</strong><span>構成全体 {result?.counts.devices??'—'}台 / 表示対象 {result?.display.counts.devices??'—'}台・{result?.display.counts.rows??'—'}行{pending?'（更新待ち）':''}</span><button onClick={()=>onChange(emptyScope())}>絞り込みを解除</button></div>
  <div className="scope-fields">{facet('site',result?.catalog.sites??[])}{facet('group',result?.catalog.groups??[])}
   <label>機器<select aria-label="表示する機器" value={scope.device_ids[0]??''} onChange={e=>onChange({...scope,device_ids:e.target.value?[e.target.value]:[],trace_root:null})}><option value="">すべて</option>{missing.map(id=><option key={id} value={id}>{id}（表示条件外）</option>)}{candidates.map(d=><option key={d.id} value={d.id}>{d.name} / {d.id}</option>)}</select></label>
   <label>対応関係の起点<select aria-label="表示する対応関係" value={rootValue} onChange={e=>onFocus(e.target.value?JSON.parse(e.target.value):null)}><option value="">すべての行</option>{scope.trace_root&&!knownRoot&&<option value={rootValue}>{scope.trace_root.layer.toUpperCase()} / {scope.trace_root.id}</option>}{roots.map(r=><option key={r.layer+r.id} value={JSON.stringify({layer:r.layer,id:r.id})}>{r.label}</option>)}</select></label>
  </div>
  <p>条件は組み合わせて適用します。機器を1台に絞ると、図が表示できない場合もポート・インターフェースから対応関係を選べます。YAMLの内容は変わりません。</p>
  <details className="scope-limits"><summary>描画の上限：{limits.view_devices}台・{limits.view_rows}行・接続／所属 {limits.view_connections}件</summary><p>表示中のレイヤーで構成要素 {limits.view_elements}件、VLAN・ブリッジ・サブネット {limits.view_groups}件、SVG {sizeLabel(limits.svg_bytes)}まで。上限を超える場合は一部を自動で間引かず、条件の変更を案内します。trunkのVLAN所属もそれぞれ接続1件として数えます。</p></details>
  {result?.display.filtered&&<p className="scope-partial">構成の一部を表示しています。同じVLAN・サブネットでも範囲外の機器は表示されません。</p>}
  {!!result?.display.boundary_links.total&&<details className="scope-boundary"><summary>範囲外へつながる{result.display.boundary_links.noun} {result.display.boundary_links.total}本（図から省略）</summary><ul>{result.display.boundary_links.items.map(b=><li key={b.id}><code>{b.id}</code>〔{b.kind==='wifi'?'Wi-Fi':'有線'} / {{confirmed:'両端確認済み',port_unknown:'ポート／無線IF未確認',peer_unknown:'接続先未確認'}[b.status]}〕：{b.local} ↔ {b.remote}{b.remote_device&&<>（機器 {b.remote_device}）</>}{b.ssid&&<> / SSID: {b.ssid}</>}{b.observed_at&&<> / 確認: {b.observed_at}</>}</li>)}</ul>{result.display.boundary_links.has_more&&<p>先頭100件を表示しています。全接続はYAMLで確認できます。</p>}</details>}
 </section>;
}
