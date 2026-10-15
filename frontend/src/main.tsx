import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {basicSetup} from 'codemirror';
import {EditorView, keymap} from '@codemirror/view';
import {EditorState} from '@codemirror/state';
import {yaml} from '@codemirror/lang-yaml';
import {setDiagnostics} from '@codemirror/lint';
import './style.css';

type Issue = {message:string; path:string; line:number|null; column:number|null};
type Result = {svg:string; devices:{id:string;name:string}[]; counts:{devices:number;links:number;vlans:number}};
type View = 'all'|'l1'|'l2'|'l3';
const encoder = new TextEncoder();
const maxBytes = 262144;
const LABELS = {all:'全レイヤー',l1:'L1 物理',l2:'L2 VLAN',l3:'L3 IP'};

function App() {
  const [source,setSource] = useState('');
  const [filename,setFilename] = useState('lan-sample.yaml');
  const [view,setView] = useState<View>('all');
  const [bindings,setBindings] = useState(true);
  const [result,setResult] = useState<Result|null>(null);
  const [issues,setIssues] = useState<Issue[]>([]);
  const [phase,setPhase] = useState<'loading'|'pending'|'valid'|'invalid'>('loading');
  const [notice,setNotice] = useState('');
  const [selected,setSelected] = useState('');
  const [zoom,setZoom] = useState(0.6);
  const [dirty,setDirty] = useState(false);
  const editorMount = useRef<HTMLDivElement>(null);
  const editor = useRef<EditorView|null>(null);
  const canvas = useRef<HTMLDivElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const file = useRef<HTMLInputElement>(null);
  const sequence = useRef(0);
  const currentController = useRef<AbortController|null>(null);
  const latest = useRef<{source:string; view:View; bindings:boolean}>({source:'',view:'all',bindings:true});
  const saved = useRef('');
  const fitPending = useRef(true);
  const sourceRef = useRef('');
  const invalidate = () => { sequence.current++; currentController.current?.abort(); setPhase('pending'); };
  const changeSource = (value:string, user=true) => {
    invalidate(); sourceRef.current = value; latest.current.source=value;
    setSource(value); setDirty(user && value!==saved.current);
  };
  const replaceSource = (value:string) => {
    changeSource(value,false); saved.current=value; setDirty(false);
    const ed = editor.current;
    if(ed) ed.dispatch({changes:{from:0,to:ed.state.doc.length,insert:value}});
  };

  useEffect(()=>{
    if(!editorMount.current) return;
    const ed = new EditorView({parent:editorMount.current,state:EditorState.create({doc:'',extensions:[
      basicSetup, yaml(),
      EditorView.contentAttributes.of({'aria-label':'YAMLエディター','spellcheck':'false'}),
      keymap.of([{key:'Mod-s',run:()=>{document.getElementById('save-yaml')?.click();return true;}}]),
      EditorView.updateListener.of(update=>{if(update.docChanged){const next=update.state.doc.toString();if(next!==sourceRef.current) changeSource(next);}}),
      EditorView.theme({'&':{height:'100%',fontSize:'12px'},'.cm-scroller':{overflow:'auto',fontFamily:'ui-monospace, Consolas, monospace',lineHeight:'1.8'},'.cm-content':{padding:'14px 0'},'.cm-gutters':{background:'#f6f8fa',color:'#98a3af',borderRight:'1px solid #e7ebef'},'.cm-activeLine':{background:'#edf5f3'},'.cm-activeLineGutter':{background:'#e6efec'},'&.cm-focused':{outline:'none'}})
    ]})});
    editor.current=ed;
    let active=true;
    fetch('/api/sample').then(r=>{if(!r.ok)throw Error();return r.json();}).then(data=>{if(active)replaceSource(data.yaml_text);}).catch(()=>{if(active){setPhase('invalid');setIssues([{message:'サンプルを読み込めません。接続を確認して再読み込みしてください。',path:'',line:null,column:null}]);}});
    return ()=>{active=false;ed.destroy();editor.current=null;};
  },[]);

  useEffect(()=>{
    if(!source && phase==='loading')return;
    latest.current={source,view,bindings};
    const revision=++sequence.current;
    const controller=new AbortController(); currentController.current=controller;
    const timer=window.setTimeout(async()=>{
      try {
        if(encoder.encode(source).length>maxBytes)throw new Error('YAMLは256 KiB以下にしてください');
        const response=await fetch('/api/render',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({yaml_text:source,view,show_bindings:bindings}),signal:controller.signal});
        const body=await response.json();
        if(revision!==sequence.current)return;
        if(!response.ok){setIssues(body.errors??[{message:'描画できませんでした',path:'',line:null,column:null}]);setPhase('invalid');return;}
        setResult(body);setIssues([]);setPhase('valid');
      } catch(error) {
        if(controller.signal.aborted || revision!==sequence.current)return;
        setIssues([{message:error instanceof Error && error.message.includes('KiB')?error.message:'サーバーへ接続できません。編集内容を保存して、接続を確認してください。',path:'',line:null,column:null}]);setPhase('invalid');
      }
    },500);
    return ()=>{window.clearTimeout(timer);controller.abort();};
  },[source,view,bindings]);

  useEffect(()=>{
    const ed=editor.current;if(!ed)return;
    ed.dispatch(setDiagnostics(ed.state,issues.filter(i=>i.line && i.line<=ed.state.doc.lines).map(i=>{
      const line=ed.state.doc.line(i.line!);return {from:Math.min(line.to,line.from+Math.max(0,(i.column??1)-1)),to:line.to,severity:'error' as const,message:(i.path?i.path+': ':'')+i.message};
    })));
  },[issues]);

  useEffect(()=>{
    if(!canvas.current || !result)return;
    const nodes=canvas.current.querySelectorAll<SVGGElement>('g[data-device]');
    nodes.forEach(n=>{n.classList.toggle('selected-device',!!selected && n.dataset.device===selected);n.classList.toggle('other-device',!!selected && n.dataset.device!==selected);});
    if(selected && !result.devices.some(d=>d.id===selected))setSelected('');
    if(fitPending.current && viewport.current){setZoom(Math.min(1,(viewport.current.clientWidth-64)/dimensions.width));fitPending.current=false;}
  },[result,selected]);

  useEffect(()=>{
    const warn=(e:BeforeUnloadEvent)=>{if(dirty){e.preventDefault();}};
    window.addEventListener('beforeunload',warn);return ()=>window.removeEventListener('beforeunload',warn);
  },[dirty]);

  const dimensions=(()=>{const m=result?.svg.match(/viewBox="0 0 ([\d.]+) ([\d.]+)"/);return {width:Number(m?.[1]??1520),height:Number(m?.[2]??1000)};})();
  const download=(body:string,name:string,type:string)=>{const url=URL.createObjectURL(new Blob([body],{type}));const anchor=document.createElement('a');anchor.href=url;anchor.download=name;anchor.click();window.setTimeout(()=>URL.revokeObjectURL(url),1000);};
  const saveYaml=()=>{download(source,filename,'application/yaml;charset=utf-8');saved.current=source;setDirty(false);setNotice('YAMLをダウンロードしました');};
  const fit=()=>{if(viewport.current)setZoom(Math.max(.1,Math.min(1,(viewport.current.clientWidth-64)/dimensions.width,(viewport.current.clientHeight-64)/dimensions.height)));};
  const openFile=async(e:React.ChangeEvent<HTMLInputElement>)=>{const f=e.target.files?.[0];e.target.value='';if(!f)return;if(f.size>maxBytes){setNotice('ファイルは256 KiB以下にしてください');return;}if(dirty&&!window.confirm('未保存の編集内容を置き換えますか？'))return;replaceSource(await f.text());setFilename(f.name);setNotice('ファイルを読み込みました');};
  const selectElement=(target:EventTarget|null)=>{const group=(target as Element)?.closest?.('[data-device]');if(group){const id=group.getAttribute('data-device')??'';setSelected(previous=>previous===id?'':id);}};
  const jump=(issue:Issue)=>{const ed=editor.current;if(!ed||!issue.line||issue.line>ed.state.doc.lines)return;ed.dispatch({selection:{anchor:ed.state.doc.line(issue.line).from},scrollIntoView:true});ed.focus();};

  return <div className="app">
    <header className="app-header">
      <a className="brand" href="/" aria-label="LayerMap ホーム"><span className="brand-mark"><i/><i/><i/></span><span>Layer<span className="brand-light">Map</span></span><span className="version">PREVIEW</span></a>
      <div className="header-note"><span className="live-dot"/>NETWORK WORKSPACE</div>
      <div className="file-actions">
        <input ref={file} type="file" accept=".yaml,.yml,text/yaml,application/yaml" onChange={openFile} hidden/>
        <button onClick={()=>file.current?.click()}><span aria-hidden="true">↥</span> YAMLを開く</button>
        <button id="save-yaml" onClick={saveYaml}><span aria-hidden="true">↓</span> YAMLを保存</button>
        <button className="primary" disabled={!result||phase!=='valid'} onClick={()=>result&&download(result.svg,filename.replace(/\.(yaml|yml)$/i,'')+'-'+view+'.svg','image/svg+xml;charset=utf-8')}>SVGを書き出す <span aria-hidden="true">↗</span></button>
      </div>
    </header>
    <section className="workspace-heading">
      <div><div className="eyebrow">NETWORK / LAYERED VIEW</div><h1>ネットワーク ワークスペース</h1><p>ひとつのYAMLから、物理接続と論理構成をつなぐ。</p></div>
      <div className="scope-pill"><span/> L1 <b>·</b> L2 <b>·</b> L3</div>
    </section>
    <main className="workspace">
      <section className="editor-panel" aria-label="構成データ">
        <div className="panel-header"><div><span className="file-icon">≡</span> 構成データ <span className="file-type">YAML</span></div><span className={'saved '+(dirty?'unsaved':'')}>{dirty?'● 未保存':'保存済み'}</span></div>
        <div className="filename-row"><span>{filename}</span><span>{encoder.encode(source).length.toLocaleString()} bytes</span></div>
        <div className="editor" ref={editorMount}/>
        <div className="editor-bottom"><span>UTF-8</span><span>256 KiBまで · Ctrl / ⌘ + S で保存</span></div>
      </section>
      <section className="preview-panel" aria-label="ネットワーク図">
        <div className="preview-toolbar">
          <div className="tabs" role="tablist" aria-label="表示レイヤー">{(Object.keys(LABELS) as View[]).map(v=><button key={v} role="tab" aria-selected={view===v} className={view===v?'active':''} onClick={()=>{if(v!==view){invalidate();latest.current.view=v;setView(v);fitPending.current=true;}}}>{LABELS[v]}</button>)}</div>
          <label className="toggle-label"><input type="checkbox" checked={bindings} disabled={view!=='all'} onChange={e=>{invalidate();latest.current.bindings=e.target.checked;setBindings(e.target.checked);}}/><span className="toggle-track"/> 層間対応</label>
        </div>
        <div className="preview-info"><span className="preview-label"><span className="live-dot"/> DIAGRAM PREVIEW</span><label>機器 <select aria-label="機器の強調表示" value={selected} onChange={e=>setSelected(e.target.value)}><option value="">すべて表示</option>{result?.devices.map(d=><option value={d.id} key={d.id}>{d.name}</option>)}</select></label></div>
        <div className="viewport" ref={viewport}>
          {phase!=='valid'&&result&&<div className={'stale-banner '+(phase==='invalid'?'error':'')} role="status">{phase==='invalid'?'現在のYAMLは未反映です。最後に正常生成した図を表示しています。':'更新待ち · 最後に正常生成した図を表示しています。'}</div>}
          {!result?<div className="empty-state"><span className="empty-glyph">▱</span><h2>{phase==='invalid'?'構成データを確認してください':'図面を準備しています'}</h2><p>YAMLを検証して、レイヤーごとの構成を描画します。</p></div>:<div className="diagram-space" style={{width:dimensions.width*zoom+64,height:dimensions.height*zoom+64}}><div ref={canvas} className="diagram" data-testid="diagram" style={{width:dimensions.width,height:dimensions.height,transform:'scale('+zoom+')'}} onClick={e=>selectElement(e.target)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectElement(e.target);}}} dangerouslySetInnerHTML={{__html:result.svg}}/></div>}
        </div>
        <div className="preview-bottom"><div className="legend"><span><i className="line-solid"/>レイヤー内の関係</span><span><i className="line-dash"/>層間の対応</span></div><div className="zoom-controls"><button aria-label="縮小" onClick={()=>setZoom(z=>Math.max(.1,z-.1))}>−</button><span>{Math.round(zoom*100)}%</span><button aria-label="拡大" onClick={()=>setZoom(z=>Math.min(2,z+.1))}>＋</button><button onClick={fit}>全体表示</button></div></div>
      </section>
    </main>
    <section className={'validation '+phase} aria-live="polite" aria-label="検証結果"><div className="validation-title"><span className="status-icon">{phase==='valid'?'✓':phase==='invalid'?'!':'◌'}</span><strong>{phase==='valid'?'検証済み':phase==='invalid'?'入力を確認してください':phase==='loading'?'読み込み中':'更新待ち'}</strong>{phase==='valid'&&result&&<span className="counts">{result.counts.devices} 機器 <b>·</b> {result.counts.links} ケーブル <b>·</b> {result.counts.vlans} VLAN</span>}<span className="validation-hint">{phase==='valid'?'最新のYAMLを図面に反映しました':'編集が止まると自動で検証します'}</span></div>{issues.map((issue,n)=><button className="issue" key={n} onClick={()=>jump(issue)}>{issue.line&&<span>{issue.line}行{issue.column?':'+issue.column:''}</span>}<code>{issue.path}</code>{issue.message}</button>)}</section>
    <footer><span>LayerMap <b>·</b> 構成の意味を、ひとつに。</span><span>YAMLは描画のためサーバーへ送信されます。永続保存はしません。</span></footer>
    {notice&&<div className="toast" role="status" onClick={()=>setNotice('')}>{notice}<button aria-label="通知を閉じる" onClick={()=>setNotice('')}>×</button></div>}
  </div>;
}

createRoot(document.getElementById('root')!).render(<App/>);
