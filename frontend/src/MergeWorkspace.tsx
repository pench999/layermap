import React,{useEffect,useRef,useState} from 'react';
import {requestJson} from './InputSupport';
type Source={key:number;site_id:string;filename:string;yaml_text:string;blob:Blob};
type Mapping={site_id:string;section:string;original:string;converted:string};
type Finding={kind:string;message:string;items:{site_id:string;filename:string;id:string;address?:string;cidr?:string}[];total:number};
type Merged={yaml_text:string;filename:string;mapping:Mapping[];sources:{site_id:string;filename:string;devices:number;renamed:number;previous_sites:string[]}[];issues:Finding[];issue_count:number;issues_truncated:boolean;id_collisions:number;counts:{devices:number;elements:number;sites:number}};
type Diagram={svg:string;display:{status:string;message:string;counts:{devices:number;rows:number}}};
type View='all'|'l1'|'l2'|'l3';
const bytes=new TextEncoder();
function save(blob:Blob,name:string){const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
export function MergeWorkspace({source,maxBytes,onApply}:{source:string;maxBytes:number;onApply:(base:string,text:string,site:string,view:View)=>boolean}){
 const [open,setOpen]=useState(false),[sources,setSources]=useState<Source[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(false),[fileBusy,setFileBusy]=useState(false);
 const [result,setResult]=useState<Merged|null>(null),[base,setBase]=useState(''),[site,setSite]=useState(''),[view,setView]=useState<View>('all'),[diagram,setDiagram]=useState<Diagram|null>(null),[diagramError,setDiagramError]=useState(''),[drawing,setDrawing]=useState(false),[zoom,setZoom]=useState(.45),[query,setQuery]=useState('');
 const dialog=useRef<HTMLDialogElement>(null),file=useRef<HTMLInputElement>(null),controller=useRef<AbortController|null>(null),revision=useRef(0),readRevision=useRef(0),key=useRef(0),currentSource=useRef(source);currentSource.current=source;
 const invalidate=()=>{revision.current++;controller.current?.abort();setResult(null);setDiagram(null);setDiagramError('');setError('');setBusy(false);};
 useEffect(()=>{if(open)dialog.current?.showModal();},[open]);
 useEffect(()=>{invalidate();},[source]);
 useEffect(()=>()=>{controller.current?.abort();readRevision.current++;},[]);
 const close=()=>{controller.current?.abort();revision.current++;readRevision.current++;setBusy(false);setFileBusy(false);setOpen(false);};
 const total=sources.reduce((n,s)=>n+bytes.encode(s.yaml_text).length,0);
 const validSites=sources.every(s=>/^[a-z][a-z0-9_-]{0,31}$/.test(s.site_id))&&new Set(sources.map(s=>s.site_id)).size===sources.length;
 const addFiles=async(selected:File[])=>{
  if(!selected.length)return;
  if(sources.length+selected.length>16){setError('統合元は16ファイルまでです。');return;}
  if(selected.some(f=>f.size>maxBytes)||sources.reduce((n,s)=>n+s.blob.size,0)+selected.reduce((n,f)=>n+f.size,0)>maxBytes){setError('統合元ファイルの合計は2 MiB以下にしてください。');return;}
  invalidate();setFileBusy(true);const read=++readRevision.current;
  const loaded=await Promise.allSettled(selected.map(async f=>({file:f,text:new TextDecoder('utf-8',{fatal:true}).decode(await f.arrayBuffer())})));
  if(read!==readRevision.current)return;
  const added=loaded.filter((r):r is PromiseFulfilledResult<{file:File;text:string}>=>r.status==='fulfilled').map(r=>r.value);
  setSources(existing=>{const used=new Set(existing.map(s=>s.site_id));return [...existing,...added.map(item=>{const k=++key.current;const stem=item.file.name.replace(/\.ya?ml$/i,'').toLowerCase().replace(/[^a-z0-9_-]/g,'-').slice(0,24);let id=/^[a-z]/.test(stem)?stem:'site'+k;let suffix=1;const start=id;while(used.has(id))id=start+'-'+suffix++;used.add(id);return {key:k,site_id:id,filename:item.file.name,yaml_text:item.text,blob:item.file};})];});
  setFileBusy(false);if(added.length!==selected.length)setError('UTF-8として読めないファイル: '+loaded.flatMap((r,n)=>r.status==='rejected'?[selected[n].name]:[]).join('、')+'。読めたファイルは保持しています。');
 };
 const loadSamples=async()=>{
  invalidate();readRevision.current++;const seq=revision.current;const c=new AbortController();controller.current=c;setBusy(true);
  try{const response=await fetch('/api/merge/sample',{signal:c.signal});if(!response.ok)throw Error('統合サンプルを取得できませんでした。');const data=await response.json();if(seq!==revision.current)return;
   setSources(data.sources.map((s:{site_id:string;filename:string;yaml_text:string})=>({...s,key:++key.current,blob:new Blob([s.yaml_text],{type:'application/yaml;charset=utf-8'})})));setQuery('');
  }catch(e){if(!c.signal.aborted)setError(e instanceof Error?e.message:'サンプルを取得できませんでした。');}finally{if(seq===revision.current)setBusy(false);}
 };
 const verify=async()=>{
  invalidate();const seq=revision.current;const snapshot=source;const c=new AbortController();controller.current=c;setBusy(true);setQuery('');
  try{const payload={sources:sources.map(({site_id,filename,yaml_text})=>({site_id,filename,yaml_text}))};if(bytes.encode(JSON.stringify(payload)).length>8*1024*1024)throw Error('JSON化したリクエストが8 MiBを超えます。ファイルを分けてください。');
   const data=await requestJson('/api/merge/preview',payload,c.signal);if(seq!==revision.current||currentSource.current!==snapshot)return;setResult(data);setBase(snapshot);setSite('');setView('all');setZoom(.45);
  }catch(e){if(!c.signal.aborted)setError(e instanceof Error?e.message:'統合できませんでした。');}finally{if(seq===revision.current)setBusy(false);}
 };
 useEffect(()=>{
  if(!open||!result){setDiagram(null);setDrawing(false);return;}
  const c=new AbortController();setDiagram(null);setDiagramError('');setDrawing(true);
  requestJson('/api/render',{yaml_text:result.yaml_text,view,show_bindings:true,scope:site?{site}:{}},c.signal).then(data=>{if(!c.signal.aborted)setDiagram(data);}).catch(e=>{if(!c.signal.aborted)setDiagramError(e instanceof Error?e.message:'図面を生成できませんでした。');}).finally(()=>{if(!c.signal.aborted)setDrawing(false);});
  return()=>c.abort();
 },[result,site,view,open]);
 const dimensions=(()=>{const match=diagram?.svg.match(/viewBox="0 0 ([\d.]+) ([\d.]+)"/);return {width:Number(match?.[1]??1000),height:Number(match?.[2]??800)};})();
 const matches=result?.mapping.filter(m=>!query||[m.site_id,m.section,m.original,m.converted].some(s=>s.toLowerCase().includes(query.toLowerCase())))??[];
 return <>
 <section className="merge-entry" aria-label="拠点YAMLの統合"><strong>拠点別YAML</strong><button onClick={()=>{setError('');setOpen(true);}}>複数YAMLを統合</button><span>{sources.length?'統合元 '+sources.length+' 件をこの画面で保持しています':'元ファイルを保持し、拠点IDで参照を変換して統合できます'}</span></section>
 {open&&<dialog ref={dialog} className="merge-dialog" aria-label="拠点YAMLの統合" onCancel={e=>{e.preventDefault();close();}}>
 <div className="input-heading"><h2>拠点YAMLの統合</h2><button aria-label="統合画面を閉じる" onClick={close}>×</button></div>
 <p>元ファイルは変更しません。統合結果は独立したYAMLとして生成します。編集中の統合YAMLの変更を元ファイルへ書き戻すことはありません。</p>
 <p className="merge-note">機器などのIDと参照を「拠点ID::元ID」に変換し、location.siteを拠点IDに揃えます。機器名・IP・VLAN番号・機器群は維持します。拠点間の接続は自動追加しません。</p>
 <div className="merge-tools"><input ref={file} type="file" multiple accept=".yaml,.yml,text/yaml,application/yaml" aria-label="統合元YAMLを追加" hidden onChange={e=>{const selected=Array.from(e.target.files??[]);e.target.value='';void addFiles(selected);}}/><button disabled={busy||fileBusy} onClick={()=>file.current?.click()}>YAMLファイルを追加</button><button disabled={busy||fileBusy} onClick={()=>{if(!sources.length||window.confirm('選択中の統合元をサンプル2件に置き換えますか？'))void loadSamples();}}>統合サンプルをセット</button><button disabled={busy||fileBusy||!sources.length} onClick={()=>{invalidate();readRevision.current++;setSources([]);}}>統合元をすべて外す</button><span>{sources.length} / 16 ファイル · {(total/1024).toFixed(1)} KiB / 2 MiB</span></div>
 {error&&<p role="alert" className="input-error">{error}</p>}
 <div className="merge-sources">{sources.map((s,n)=><article key={s.key} aria-label={'統合元 '+(n+1)}><div><strong>{s.filename}</strong><span>{s.blob.size.toLocaleString()} bytes</span></div><label>拠点ID（英小文字・数字・_・-、先頭は英小文字）<input aria-label={'拠点ID '+s.filename} maxLength={32} value={s.site_id} disabled={busy||fileBusy} onChange={e=>{invalidate();setSources(items=>items.map(item=>item.key===s.key?{...item,site_id:e.target.value}:item));}}/></label><div className="merge-tools"><button onClick={()=>save(s.blob,s.filename)}>元ファイルを保存：{s.filename}</button><button disabled={busy||fileBusy} onClick={()=>{invalidate();setSources(items=>items.filter(item=>item.key!==s.key));}}>外す</button></div><details><summary>元YAMLを確認（読み取り専用）</summary><pre className="merge-source-code">{s.yaml_text}</pre></details></article>)}</div>
 {!!sources.length&&!validSites&&<p className="input-error">拠点IDの形式または重複を確認してください。</p>}
 <div className="merge-tools"><button className="primary" disabled={busy||fileBusy||sources.length<2||!validSites||total>maxBytes} onClick={()=>void verify()}>{busy?'検証中…':'統合を検証してプレビュー'}</button><span>{fileBusy?'ファイルを読み込み中…':'各ファイルを単独で検証した後、参照変換と統合後の全体検証を行います。'}</span></div>
 {result&&<section className="merge-review" aria-label="統合結果の確認"><h3>統合結果の確認</h3><p><strong>{result.counts.sites} 拠点・{result.counts.devices} 機器・{result.counts.elements} 要素</strong> · {result.mapping.length} IDを変換（元IDの拠点間重複 {result.id_collisions} 件）</p>
 <ul>{result.sources.map(s=><li key={s.site_id}>{s.filename} → 拠点 {s.site_id}：{s.devices}機器・{s.renamed} ID変換。location.siteの旧値：{s.previous_sites.map(v=>v||'未設定').join('、')||'変更なし'}</li>)}</ul>
 <section aria-label="重複と確認事項"><h4>重複と確認事項（{result.issue_count} 件）</h4><p>以下は自動修正しません。同じ番号・アドレスでも拠点別に保持します。不正な参照など、統合を妨げる不整合がある場合はプレビューを生成しません。</p>{!result.issue_count&&<p>検出した重複・確認事項はありません。</p>}{result.issues.map((issue,n)=><details className={'merge-finding '+(issue.kind==='same_vlan_tag'||issue.kind==='notes_display_limit'?'info':'')} key={n}><summary>{issue.message} {issue.total>0&&'（'+issue.total+'件）'}</summary><ul>{issue.items.map((item,i)=><li key={i}>{item.site_id} / {item.filename} / {item.id}{item.address?' / '+item.address:''}{item.cidr?' / '+item.cidr:''}</li>)}</ul>{issue.total>issue.items.length&&<p>詳細は先頭{issue.items.length}件を表示しています。</p>}</details>)}{result.issues_truncated&&<p>確認事項は先頭200件まで表示しています。総数は{result.issue_count}件です。</p>}</section>
 <details><summary>ID変換一覧（{result.mapping.length} 件）</summary><label>変換一覧を検索<input aria-label="変換一覧を検索" value={query} onChange={e=>setQuery(e.target.value)}/></label><div className="merge-table-scroll"><table><thead><tr><th>拠点</th><th>項目</th><th>元ID</th><th>変換後ID</th></tr></thead><tbody>{matches.slice(0,100).map(m=><tr key={m.site_id+'|'+m.section+'|'+m.original}><td>{m.site_id}</td><td>{m.section}</td><td>{m.original}</td><td>{m.converted}</td></tr>)}</tbody></table></div><p>{matches.length}件中先頭100件まで表示。すべての変換は「確認レポートを保存」で取得できます。</p></details>
 <section aria-label="統合図面プレビュー"><h4>統合図面プレビュー</h4><div className="merge-tools"><label>プレビューする拠点<select aria-label="プレビューする拠点" value={site} onChange={e=>setSite(e.target.value)}><option value="">すべて</option>{result.sources.map(s=><option key={s.site_id} value={s.site_id}>{s.site_id}</option>)}</select></label><label>プレビューするレイヤー<select aria-label="プレビューするレイヤー" value={view} onChange={e=>setView(e.target.value as View)}><option value="all">全レイヤー</option><option value="l1">L1 物理</option><option value="l2">L2 VLAN</option><option value="l3">L3 IP</option></select></label><button aria-label="統合プレビューを縮小" onClick={()=>setZoom(v=>Math.max(.1,v-.1))}>−</button><span>{Math.round(zoom*100)}%</span><button aria-label="統合プレビューを拡大" onClick={()=>setZoom(v=>Math.min(1.5,v+.1))}>＋</button></div>
 {drawing?<p role="status">図面を生成中…</p>:diagramError?<p role="alert" className="input-error">{diagramError}</p>:diagram?.svg?<div className="merge-diagram-scroll"><div style={{width:dimensions.width*zoom+32,height:dimensions.height*zoom+32}}><div data-testid="merge-diagram" style={{width:dimensions.width,height:dimensions.height,transform:'scale('+zoom+')',transformOrigin:'top left'}} dangerouslySetInnerHTML={{__html:diagram.svg}}/></div></div>:diagram&&<p>{diagram.display.message} プレビューの拠点を選んでください。統合YAML全体は保持されています。</p>}
 {diagram&&<p>表示対象：{diagram.display.counts.devices} 機器・{diagram.display.counts.rows} 行。機器群や個別機器による絞り込みは編集画面で利用できます。</p>}</section>
 <details><summary>統合YAMLプレビュー</summary><textarea aria-label="統合YAMLプレビュー" readOnly value={result.yaml_text}/><p>統合YAMLは再生成した書式です。元のコメント・書式は上の元ファイル保存で保持できます。元のname・scope・全注記は統合YAMLのsourceコメントにも記録しています。</p></details>
 <div className="merge-actions"><button onClick={()=>save(new Blob([result.yaml_text],{type:'application/yaml;charset=utf-8'}),result.filename)}>統合YAMLを保存</button><button onClick={()=>save(new Blob([JSON.stringify({sources:result.sources,mapping:result.mapping,issues:result.issues,issue_count:result.issue_count,issues_truncated:result.issues_truncated},null,2)],{type:'application/json'}),'layermap-merge-report.json')}>確認レポートを保存</button><button className="primary" disabled={source!==base||busy||fileBusy} onClick={()=>{if(onApply(base,result.yaml_text,site,view))close();else setError('読み込みを中止しました。編集中のYAMLが変わった場合は、プレビューを作り直してください。');}}>編集画面へ読み込む</button></div>
 </section>}
 <p className="merge-note">統合元はこの画面を閉じても保持します。ブラウザを再読み込みすると保持は終了します。検証時はサーバーへ送信しますが、永続保存しません。</p>
 <div className="merge-actions"><button onClick={close}>閉じる</button></div>
 </dialog>}
 </>;
}
