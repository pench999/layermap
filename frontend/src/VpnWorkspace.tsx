import {useEffect,useRef,useState} from 'react';
import {requestJson,type Proposal} from './InputSupport';
import type {Result} from './scope';
function save(text:string,name:string){const url=URL.createObjectURL(new Blob([text],{type:'application/yaml;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
type Preview=Proposal&{added:number;total:number;message:string};
export function VpnWorkspace({source,maxBytes,onApply,onSample}:{source:string;maxBytes:number;onApply:(base:string,p:Proposal)=>boolean;onSample:(base:string,text:string,site:string,view:'all'|'l3')=>boolean}){
 const [open,setOpen]=useState(false),[text,setText]=useState('schema: layermap-vpn/v1\nvpn_connections: []\n'),[original,setOriginal]=useState(''),[name,setName]=useState('vpn-connections.yaml');
 const [sample,setSample]=useState<string|null>(null),[preview,setPreview]=useState<Preview|null>(null),[drawing,setDrawing]=useState<Result|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const dialog=useRef<HTMLDialogElement>(null),file=useRef<HTMLInputElement>(null),abort=useRef<AbortController|null>(null),seq=useRef(0),current=useRef(source);current.current=source;
 const reset=()=>{seq.current++;abort.current?.abort();setPreview(null);setDrawing(null);setError('');setBusy(false);};
 useEffect(()=>{reset();},[source]);
 useEffect(()=>{if(open)dialog.current?.showModal();return()=>{abort.current?.abort();};},[open]);
 const close=()=>{reset();setOpen(false);};
 const loadSample=async()=>{reset();const n=seq.current;setBusy(true);const c=new AbortController();abort.current=c;try{const r=await fetch('/api/vpn/sample',{signal:c.signal});if(!r.ok)throw Error('サンプルを取得できません');const d=await r.json();if(n!==seq.current)return;setSample(d.yaml_text);setText(d.connections_yaml);setOriginal(d.connections_yaml);setName('10-vpn-connections.yaml');}catch(e){if(!c.signal.aborted)setError(String(e));}finally{if(n===seq.current)setBusy(false);}};
 const verify=async()=>{reset();const n=seq.current,base=source;setBusy(true);const c=new AbortController();abort.current=c;try{const p=await requestJson('/api/vpn/preview',{yaml_text:sample??base,connections_yaml:text},c.signal) as Preview;const d=await requestJson('/api/render',{yaml_text:p.yaml_text,view:'all',show_bindings:true},c.signal) as Result;if(n!==seq.current||current.current!==base)return;setPreview(p);setDrawing(d);}catch(e){if(!c.signal.aborted)setError(e instanceof Error?e.message:String(e));}finally{if(n===seq.current)setBusy(false);}};
 return <section className="vpn-workspace"><strong>拠点間VPN</strong><span>拠点YAMLを統合した後、別の接続定義を追加します。</span><button onClick={()=>setOpen(true)}>VPN接続定義を読み込む</button>
 {open&&<dialog ref={dialog} className="help-dialog vpn-dialog" aria-labelledby="vpn-title" onCancel={e=>{e.preventDefault();close();}}><header className="help-header"><div><h2 id="vpn-title">拠点間VPNの接続定義</h2><p>元ファイルを保持し、検証・プレビュー後に追加します。</p></div><button onClick={close}>閉じる</button></header><div className="vpn-content">
 <div className="vpn-actions"><button disabled={busy} onClick={()=>file.current?.click()}>接続YAMLを開く</button><button disabled={busy} onClick={loadSample}>VPNサンプルをセット</button><button onClick={()=>save(text,name)}>接続YAMLを保存</button>{original&&<button onClick={()=>save(original,name)}>元の接続YAMLを保存</button>}</div>
 <input hidden ref={file} type="file" accept=".yaml,.yml" aria-label="VPN接続YAML" onChange={async e=>{const f=e.target.files?.[0];e.target.value='';if(!f)return;reset();const n=seq.current;if(f.size>maxBytes){setError('接続YAMLの容量上限を超えています');return;}try{const raw=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(await f.arrayBuffer());if(n!==seq.current)return;setSample(null);setText(raw);setOriginal(raw);setName(f.name);}catch{setError('接続YAMLを読み込めません');}}}/>
 {sample!==null&&<p className="vpn-sample-note">サンプル用の本社・大阪LAN（アドレス重複なし）とVPNを使用します。適用すると現在の編集画面を置き換えます。<button onClick={()=>{reset();setSample(null);}}>現在のLANを使用する</button></p>}
 <label>接続定義YAML<textarea aria-label="VPN接続定義YAML" spellCheck={false} value={text} onChange={e=>{reset();setText(e.target.value);}}/></label>
 <p>device・subnetsは統合後のID（例 hq::gw01）を参照します。ルート型はトンネルIF、ポリシー型は両端の対象サブネットを記述します。</p>
 <button className="primary" disabled={busy||!source} onClick={verify}>{busy?'検証中…':'VPNを検証してプレビュー'}</button>{error&&<p role="alert" className="sample-error">{error}</p>}
 {preview&&<section aria-label="VPN統合プレビュー"><h3>{preview.added}件を追加 / 合計{preview.total} VPN</h3><p>{preview.message}</p><p>同じVPN IDの再追加はエラーになります。適用後の変更・削除は編集画面のvpn_connectionsを編集してください。</p><details><summary>追加される定義</summary><pre>{text}</pre></details>{drawing?.svg?<div className="vpn-preview" dangerouslySetInnerHTML={{__html:drawing.svg}}/>:<p>{drawing?.display.message}</p>}<div className="vpn-actions"><button onClick={()=>save(preview.yaml_text,'layermap-with-vpn.yaml')}>VPNを含むYAMLを保存</button><button className="primary" onClick={()=>{const ok=sample!==null?onSample(source,preview.yaml_text,'','all'):onApply(source,preview);if(ok)close();else setError('編集中のYAMLが変わったか、適用が取り消されました。再度確認してください。');}}>確認したVPNを適用</button><button onClick={close}>取り消して閉じる</button></div></section>}
 </div></dialog>}
 </section>;
}
