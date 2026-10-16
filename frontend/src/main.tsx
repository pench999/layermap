import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {basicSetup} from 'codemirror';
import {EditorView, keymap} from '@codemirror/view';
import {EditorState} from '@codemirror/state';
import {yaml} from '@codemirror/lang-yaml';
import {setDiagnostics} from '@codemirror/lint';
import './style.css';
import {Help, type Sample} from './Help';
import {ScopeControls} from './ScopeControls';
import {emptyScope,defaultLimits,sizeLabel,type Scope,type Result,type Limits} from './scope';
import {endpointKey,traceFromSvg,type Endpoint,type Trace} from './trace';

type Issue = {message:string; path:string; line:number|null; column:number|null};
type View = 'all'|'l1'|'l2'|'l3';
const encoder = new TextEncoder();

const LABELS = {all:'全レイヤー',l1:'L1 物理',l2:'L2 VLAN',l3:'L3 IP'};

function App() {
  const [scope,setScope]=useState<Scope>(emptyScope);
  const [limits,setLimits]=useState<Limits>(defaultLimits);
  const [source,setSource] = useState('');
  const [filename,setFilename] = useState('lan-sample.yaml');
  const [view,setView] = useState<View>('all');
  const [bindings,setBindings] = useState(true);
  const [result,setResult] = useState<Result|null>(null);
  const [issues,setIssues] = useState<Issue[]>([]);
  const [phase,setPhase] = useState<'loading'|'pending'|'valid'|'invalid'>('loading');
  const [notice,setNotice] = useState('');
  const [selected,setSelected] = useState('');
  const [selectedBinding,setSelectedBinding] = useState<{key:string;label:string}|null>(null);
  const [selectedTrace,setSelectedTrace] = useState<Trace|null>(null);
  const pendingTrace = useRef<{root:Endpoint;source:string}|null>(null);
  const traceJumpPending = useRef(false);
  const [zoom,setZoom] = useState(0.6);
  const [dirty,setDirty] = useState(false);
  const dirtyRef = useRef(false);
  const [helpOpen,setHelpOpen] = useState(false);
  const [samples,setSamples] = useState<Sample[]>([]);
  const [sampleId,setSampleId] = useState('base');
  const [sampleLoading,setSampleLoading] = useState(false);
  const [sampleError,setSampleError] = useState('');
  const [renderEpoch,setRenderEpoch] = useState(0);
  const sampleBusy = useRef(false);
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
  const clearBinding = () => {
    setSelectedBinding(null);setSelectedTrace(null);pendingTrace.current=null;traceJumpPending.current=false;
    const focused=document.activeElement as HTMLElement|null;
    if(focused && canvas.current?.contains(focused) && focused.closest('.binding-group,.binding-badge,.interface-row'))focused.blur();
  };
  const invalidate = () => { clearBinding(); sequence.current++; currentController.current?.abort(); setPhase('pending'); };
  const changeSource = (value:string, user=true) => {
    if(value!==sourceRef.current){
      invalidate(); sourceRef.current = value; latest.current.source=value;
      setSource(value);setScope(s=>s.trace_root?{...s,trace_root:null}:s);
    }
    dirtyRef.current=user && value!==saved.current;
    setDirty(dirtyRef.current);
  };
  const replaceSource = (value:string) => {
    invalidate();setScope(emptyScope());setRenderEpoch(n=>n+1);
    changeSource(value,false); saved.current=value; dirtyRef.current=false; setDirty(false);
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
    fetch('/api/limits').then(r=>{if(!r.ok)throw Error();return r.json();}).then(data=>{if(active)setLimits(data);}).catch(()=>{});
    fetch('/api/samples').then(r=>{if(!r.ok)throw Error();return r.json();}).then(data=>{if(active)setSamples(data.samples);}).catch(()=>{if(active)setSampleError('サンプル一覧を取得できません。画面を再読み込みしてください。');});
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
        if(encoder.encode(source).length>limits.yaml_bytes)throw new Error('YAMLは'+sizeLabel(limits.yaml_bytes)+'以下にしてください');
        let response:Response;
        for(let attempt=0;;attempt++){
          response=await fetch('/api/render',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({yaml_text:source,view,show_bindings:bindings,scope}),signal:controller.signal});
          if(response.status!==429||attempt>=9)break;
          await new Promise<void>((resolve,reject)=>{const stop=()=>{window.clearTimeout(wait);reject(new DOMException('Aborted','AbortError'));};const wait=window.setTimeout(()=>{controller.signal.removeEventListener('abort',stop);resolve();},1000);controller.signal.addEventListener('abort',stop,{once:true});if(controller.signal.aborted)stop();});
        }
        const body=await response.json();
        if(revision!==sequence.current)return;
        if(!response.ok){pendingTrace.current=null;setIssues(body.errors??[{message:'描画できませんでした',path:'',line:null,column:null}]);setPhase('invalid');return;}
        const restore=pendingTrace.current;
        clearBinding();setResult(body);setLimits(body.limits);setIssues([]);setPhase('valid');
        if(restore&&restore.source===source&&view==='all'&&bindings){traceJumpPending.current=true;setSelectedTrace(traceFromSvg(body.svg,restore.root));}
      } catch(error) {
        if(controller.signal.aborted || revision!==sequence.current)return;
        pendingTrace.current=null;
        setIssues([{message:error instanceof Error && /[KM]iB/.test(error.message)?error.message:'サーバーへ接続できません。編集内容を保存して、接続を確認してください。',path:'',line:null,column:null}]);setPhase('invalid');
      }
    },500);
    return ()=>{window.clearTimeout(timer);controller.abort();};
  },[source,view,bindings,scope,limits.yaml_bytes,renderEpoch]);

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
    if(selected && !result.visible_devices.includes(selected))setSelected('');
    if(result.svg && fitPending.current && viewport.current){setZoom(Math.min(1,(viewport.current.clientWidth-64)/dimensions.width));fitPending.current=false;}
  },[result,selected]);

  useEffect(()=>{
    canvas.current?.querySelectorAll<SVGGElement>('[data-binding-key][role="button"]').forEach(group=>{
      const active=group.dataset.bindingKey===selectedBinding?.key;
      group.classList.toggle('selected-binding',active);
      group.setAttribute('aria-pressed',String(active));
    });
  },[result,selectedBinding]);

  useEffect(()=>{
    const svg=canvas.current?.querySelector('svg');
    svg?.classList.toggle('trace-active',!!selectedTrace);
    const nodes=new Set(selectedTrace?.nodes.map(endpointKey)??[]);
    const edges=new Set(selectedTrace?.edges.map(edge=>edge.key)??[]);
    const root=selectedTrace?endpointKey(selectedTrace.root):null;
    canvas.current?.querySelectorAll<SVGGElement>('.interface-row').forEach(row=>{
      const layer=row.closest('[data-layer]')?.getAttribute('data-layer') as Endpoint['layer'];
      const key=endpointKey({layer,id:row.dataset.elementId??''});
      row.classList.toggle('trace-row',nodes.has(key));
      row.classList.toggle('trace-root',key===root);
      row.setAttribute('aria-pressed',String(key===root));
    });
    canvas.current?.querySelectorAll<SVGGElement>('.binding-group,.binding-badge').forEach(group=>group.classList.toggle('trace-edge',edges.has(group.dataset.bindingKey??'')));
  },[result,selectedTrace]);

  useEffect(()=>{
    if(!traceJumpPending.current||!selectedTrace)return;
    let settled=0;
    const frame=window.requestAnimationFrame(()=>{settled=window.requestAnimationFrame(()=>{showTraceNode(selectedTrace.root);traceJumpPending.current=false;});});
    return ()=>{window.cancelAnimationFrame(frame);window.cancelAnimationFrame(settled);};
  },[result,selectedTrace,zoom]);

  useEffect(()=>{
    const warn=(e:BeforeUnloadEvent)=>{if(dirty){e.preventDefault();}};
    window.addEventListener('beforeunload',warn);return ()=>window.removeEventListener('beforeunload',warn);
  },[dirty]);

  const dimensions=(()=>{const m=result?.svg.match(/viewBox="0 0 ([\d.]+) ([\d.]+)"/);return {width:Number(m?.[1]??1520),height:Number(m?.[2]??1000)};})();
  const download=(body:string,name:string,type:string)=>{const url=URL.createObjectURL(new Blob([body],{type}));const anchor=document.createElement('a');anchor.href=url;anchor.download=name;anchor.click();window.setTimeout(()=>URL.revokeObjectURL(url),1000);};
  const saveYaml=()=>{download(source,filename,'application/yaml;charset=utf-8');saved.current=source;dirtyRef.current=false;setDirty(false);setNotice('YAMLをダウンロードしました');};
  const fit=()=>{if(viewport.current)setZoom(Math.max(.1,Math.min(1,(viewport.current.clientWidth-64)/dimensions.width,(viewport.current.clientHeight-64)/dimensions.height)));};
  const openFile=async(e:React.ChangeEvent<HTMLInputElement>)=>{const f=e.target.files?.[0];e.target.value='';if(!f)return;if(f.size>limits.yaml_bytes){setNotice('ファイルは'+sizeLabel(limits.yaml_bytes)+'以下にしてください');return;}if(dirty&&!window.confirm('未保存の編集内容を置き換えますか？'))return;replaceSource(await f.text());setFilename(f.name);setNotice('ファイルを読み込みました');};
  const loadSample=async(id:string):Promise<boolean>=>{
    if(sampleBusy.current)return false;
    if(dirtyRef.current&&!window.confirm('未保存の編集内容をサンプルで置き換えますか？'))return false;
    const before=sourceRef.current;
    sampleBusy.current=true;setSampleLoading(true);setSampleError('');
    try{
      const response=await fetch('/api/samples/'+encodeURIComponent(id));
      if(!response.ok)throw Error();
      const data=await response.json();
      if(sourceRef.current!==before&&!window.confirm('サンプルの取得中に編集されました。最新の編集内容を置き換えますか？'))return false;
      fitPending.current=true;setSelected('');setView('all');setBindings(true);
      replaceSource(data.yaml_text);setFilename(data.filename);setSampleId(id);
      setNotice('サンプルを読み込みました');
      return true;
    }catch{
      setSampleError('サンプルの読み込みに失敗しました。編集内容は保持されています。もう一度お試しください。');
      return false;
    }finally{sampleBusy.current=false;setSampleLoading(false);}
  };
  const changeScope=(next:Scope)=>{invalidate();setSelected('');setScope(next);fitPending.current=true;};
  const focusScope=(root:Endpoint|null)=>{
    changeScope({...scope,trace_root:root});
    if(root){pendingTrace.current={root,source:sourceRef.current};setView('all');setBindings(true);}
  };
  const startTrace=(root:Endpoint,row:SVGGElement)=>{
    if(selectedTrace&&endpointKey(selectedTrace.root)===endpointKey(root)){clearBinding();return;}
    clearBinding();setSelected('');
    if(view!=='all'||!bindings){
      invalidate();
      pendingTrace.current={root,source:sourceRef.current};
      latest.current.view='all';latest.current.bindings=true;
      setView('all');setBindings(true);fitPending.current=true;
      return;
    }
    if(result){traceJumpPending.current=true;setSelectedTrace(traceFromSvg(result.svg,root));}
    row.focus({preventScroll:true});
  };
  const selectElement=(target:EventTarget|null)=>{
    const element=target as Element|null;
    const mapping=element?.closest?.<SVGGElement>('.binding-group,.binding-badge');
    if(mapping){
      const key=mapping.dataset.bindingKey!;
      if(selectedBinding?.key===key)clearBinding();
      else{
        clearBinding();setSelected('');
        setSelectedBinding({key,label:mapping.getAttribute('aria-label')??key});
        mapping.focus({preventScroll:true});
      }
      return;
    }
    const row=element?.closest?.<SVGGElement>('.interface-row');
    if(row){
      const layer=row.closest('[data-layer]')?.getAttribute('data-layer') as Endpoint['layer'];
      startTrace({layer,id:row.dataset.elementId!},row);
      return;
    }
    clearBinding();
    const group=element?.closest?.('[data-device]');
    if(group){const id=group.getAttribute('data-device')??'';setSelected(previous=>previous===id?'':id);}
  };
  const revealRow=(row:Element|null|undefined)=>{
    const pane=viewport.current;if(!pane||!row)return;
    // SVG scrollIntoView can use unscaled coordinates inside the transformed
    // canvas. Move the HTML viewport using the actual screen-space rectangle.
    pane.scrollIntoView({block:'nearest',inline:'nearest'});
    const box=row.getBoundingClientRect(),frame=pane.getBoundingClientRect();
    const top=box.top<frame.top+8||box.bottom>frame.bottom-8?pane.scrollTop+(box.top+box.bottom-frame.top-frame.bottom)/2:pane.scrollTop;
    const left=box.left<frame.left+8||box.right>frame.right-8?pane.scrollLeft+(box.left+box.right-frame.left-frame.right)/2:pane.scrollLeft;
    pane.scrollTo({top,left,behavior:'instant'});
  };
  const focusSelectedBinding=()=>{
    const group=Array.from(canvas.current?.querySelectorAll<SVGGElement>('.binding-group')??[]).find(g=>g.dataset.bindingKey===selectedBinding?.key);
    const edge=group?.querySelector('.binding-edge');
    const layer=edge?.getAttribute('data-from-layer') as Endpoint['layer'];
    const id=edge?.getAttribute('data-from');
    if(layer&&id)focusScope({layer,id});
  };
  const showBindingEnd=(upper:boolean)=>{
    if(!selectedBinding||!canvas.current)return;
    const group=Array.from(canvas.current.querySelectorAll<SVGGElement>('.binding-group')).find(g=>g.dataset.bindingKey===selectedBinding.key);
    const layer=group?.querySelector('.binding-edge')?.getAttribute(upper?'data-from-layer':'data-to-layer');
    const row=canvas.current.querySelector('[data-layer="'+layer+'"] .binding-row-'+selectedBinding.key);
    revealRow(row);
  };
  const showTraceNode=(node:Endpoint)=>{
    const row=Array.from(canvas.current?.querySelectorAll<SVGGElement>('.interface-row')??[]).find(row=>row.dataset.elementId===node.id&&row.closest('[data-layer]')?.getAttribute('data-layer')===node.layer);
    revealRow(row);
  };
  const showTraceEdge=(key:string)=>{
    const group=Array.from(canvas.current?.querySelectorAll<SVGGElement>('.binding-group')??[]).find(group=>group.dataset.bindingKey===key);
    if(group)selectElement(group);
  };
  const jump=(issue:Issue)=>{const ed=editor.current;if(!ed||!issue.line||issue.line>ed.state.doc.lines)return;ed.dispatch({selection:{anchor:ed.state.doc.line(issue.line).from},scrollIntoView:true});ed.focus();};

  return <div className="app">
    <header className="app-header">
      <a className="brand" href="/" aria-label="LayerMap ホーム"><span className="brand-mark"><i/><i/><i/></span><span>Layer<span className="brand-light">Map</span></span><span className="version">PREVIEW</span></a>
      <div className="header-note"><span className="live-dot"/>NETWORK WORKSPACE</div>
      <div className="file-actions">
        <button className="help-trigger" onClick={()=>setHelpOpen(true)}><span aria-hidden="true">?</span> ヘルプ</button>
        <input ref={file} type="file" accept=".yaml,.yml,text/yaml,application/yaml" onChange={openFile} hidden/>
        <button onClick={()=>file.current?.click()}><span aria-hidden="true">↥</span> YAMLを開く</button>
        <button id="save-yaml" onClick={saveYaml}><span aria-hidden="true">↓</span> YAMLを保存</button>
        <button className="primary" disabled={!result?.svg||phase!=='valid'} onClick={()=>result&&download(result.svg,filename.replace(/\.(yaml|yml)$/i,'')+'-'+view+'.svg','image/svg+xml;charset=utf-8')}>SVGを書き出す <span aria-hidden="true">↗</span></button>
      </div>
    </header>
    <section className="workspace-heading">
      <div><div className="eyebrow">NETWORK / LAYERED VIEW</div><h1>ネットワーク ワークスペース</h1><p>ひとつのYAMLから、物理接続と論理構成をつなぐ。</p></div>
      <div className="scope-pill"><span/> L1 <b>·</b> L2 <b>·</b> L3</div>
    </section>
    <section className="sample-bar" aria-label="サンプルの読み込み">
      <div className="sample-controls"><label htmlFor="sample-select">サンプル構成</label><select id="sample-select" value={sampleId} disabled={!samples.length||sampleLoading} onChange={e=>setSampleId(e.target.value)}>{samples.map(s=><option value={s.id} key={s.id}>{s.title}</option>)}</select><button disabled={!samples.length||sampleLoading} onClick={()=>loadSample(sampleId)}>{sampleLoading?'読み込み中…':'サンプルを読み込む'}</button></div>
      <p>{samples.find(s=>s.id===sampleId)?.description}</p><button className="guide-link" onClick={()=>setHelpOpen(true)}>項目と追加手順 ↗</button>
      {sampleError&&<div className="sample-error" role="alert">{sampleError}</div>}
    </section>
    <main className="workspace">
      <section className="editor-panel" aria-label="構成データ">
        <div className="panel-header"><div><span className="file-icon">≡</span> 構成データ <span className="file-type">YAML</span></div><span className={'saved '+(dirty?'unsaved':'')}>{dirty?'● 未保存':'保存済み'}</span></div>
        <div className="filename-row"><span>{filename}</span><span>{encoder.encode(source).length.toLocaleString()} bytes</span></div>
        <div className="editor" ref={editorMount}/>
        <div className="editor-bottom"><span>UTF-8</span><span>{sizeLabel(limits.yaml_bytes)}まで · Ctrl / ⌘ + S で保存</span></div>
      </section>
      <section className="preview-panel" aria-label="ネットワーク図" onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();clearBinding();}}}>
        <div className="preview-toolbar">
          <div className="tabs" role="tablist" aria-label="表示レイヤー">{(Object.keys(LABELS) as View[]).map(v=><button key={v} role="tab" aria-selected={view===v} className={view===v?'active':''} onClick={()=>{if(v!==view){invalidate();latest.current.view=v;setView(v);fitPending.current=true;}}}>{LABELS[v]}</button>)}</div>
          <label className="toggle-label"><input type="checkbox" checked={bindings} disabled={view!=='all'} onChange={e=>{invalidate();latest.current.bindings=e.target.checked;setBindings(e.target.checked);}}/><span className="toggle-track"/> 層間対応</label>
        </div>
        <ScopeControls scope={scope} result={result} limits={limits} pending={phase!=='valid'} onChange={changeScope} onFocus={focusScope}/>
        <div className="preview-info"><span className="preview-label"><span className="live-dot"/> DIAGRAM PREVIEW</span><span className="trace-hint">行を選んで層間対応を追跡</span><label>機器 <select aria-label="機器の強調表示" value={selected} onChange={e=>{clearBinding();setSelected(e.target.value);}}><option value="">すべて表示</option>{result?.devices.filter(d=>result.visible_devices.includes(d.id)).map(d=><option value={d.id} key={d.id}>{d.name}</option>)}</select></label></div>
        {selectedBinding&&<div className="binding-selection" role="status" aria-label="選択した層間対応"><span>{selectedBinding.label}</span><button onClick={focusSelectedBinding}>この対応の関連行だけを表示</button><button onClick={()=>showBindingEnd(true)}>上位の行へ</button><button onClick={()=>showBindingEnd(false)}>下位の行へ</button><button onClick={clearBinding}>対応の強調を解除</button></div>}
        {selectedTrace&&<section className="trace-selection" aria-label="層間対応の追跡">
          <div className="trace-heading"><strong aria-live="polite">起点 {selectedTrace.root.layer.toUpperCase()} / {selectedTrace.root.id} · {selectedTrace.nodes.length}行・{selectedTrace.edges.length}対応</strong><button onClick={()=>focusScope(selectedTrace.root)}>この対応だけを表示</button><button onClick={clearBinding}>追跡の強調を解除</button></div>
          <p>層間対応を双方向に追跡。同じポートを共有する対応も含み、通信可能性を意味しません。</p>
          <details className="trace-details" open key={endpointKey(selectedTrace.root)}><summary>関連する行と対応（行名で移動・対応名で個別に強調）</summary>
            <div className="trace-node-list">{(['l1','l2','l3'] as const).map(layer=><div key={layer}><strong>{layer.toUpperCase()}（{selectedTrace.nodes.filter(n=>n.layer===layer).length}行）</strong>{selectedTrace.nodes.filter(n=>n.layer===layer).map(node=><button key={endpointKey(node)} className={endpointKey(node)===endpointKey(selectedTrace.root)?'trace-origin':''} onClick={()=>showTraceNode(node)}>{node.id}{endpointKey(node)===endpointKey(selectedTrace.root)?'（起点）':''} · 対応{node.degree}件</button>)}</div>)}</div>
            {selectedTrace.edges.length===0?<p>この行には層間対応の定義がありません。</p>:<div className="trace-edge-list" aria-label="追跡した対応一覧">{selectedTrace.edges.map(edge=><button key={edge.key} onClick={()=>showTraceEdge(edge.key)}>{edge.label}</button>)}</div>}
          </details>
        </section>}
        <div className="viewport" ref={viewport}>
          {phase!=='valid'&&result?.svg&&<div className={'stale-banner '+(phase==='invalid'?'error':'')} role="status">{phase==='invalid'?'現在のYAMLは未反映です。最後に正常生成した図を表示しています。':'更新待ち · 最後に正常生成した図を表示しています。'}</div>}
          {!result?<div className="empty-state"><span className="empty-glyph">▱</span><h2>{phase==='invalid'?'構成データを確認してください':'図面を準備しています'}</h2><p>YAMLを検証して、レイヤーごとの構成を描画します。</p></div>:!result.svg?<div className="empty-state" aria-label="表示範囲の案内"><span className="empty-glyph">▱</span><h2>{result.display.status==='empty'?'表示対象がありません':'表示範囲を絞り込んでください'}</h2><p>{result.display.message}</p><p>構成全体の検証は完了しています。上の「表示範囲」で条件を選んでください。</p></div>:<div className="diagram-space" style={{width:dimensions.width*zoom+64,height:dimensions.height*zoom+64}}><div ref={canvas} className="diagram" data-testid="diagram" style={{width:dimensions.width,height:dimensions.height,transform:'scale('+zoom+')'}} onClick={e=>selectElement(e.target)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectElement(e.target);}}} dangerouslySetInnerHTML={{__html:result.svg}}/></div>}
        </div>
        <div className="preview-bottom"><div className="legend"><span><i className="line-solid"/>レイヤー内の関係</span><span><i className="line-dash"/>層間の対応（選択可）</span>{result?.svg.includes('data-connection-kind=')&&<span>〜 Wi-Fi · 橙色 ? 未確認</span>}</div><div className="zoom-controls"><button aria-label="縮小" onClick={()=>setZoom(z=>Math.max(.1,z-.1))}>−</button><span>{Math.round(zoom*100)}%</span><button aria-label="拡大" onClick={()=>setZoom(z=>Math.min(2,z+.1))}>＋</button><button onClick={fit}>全体表示</button></div></div>
      </section>
    </main>
    <section className={'validation '+phase} aria-live="polite" aria-label="検証結果"><div className="validation-title"><span className="status-icon">{phase==='valid'?'✓':phase==='invalid'?'!':'◌'}</span><strong>{phase==='valid'?'検証済み':phase==='invalid'?'入力を確認してください':phase==='loading'?'読み込み中':'更新待ち'}</strong>{phase==='valid'&&result&&<span className="counts">{result.counts.devices} 機器 <b>·</b> {result.counts.links} L1接続 <b>·</b> {result.counts.vlans} VLAN</span>}<span className="validation-hint">{phase==='valid'?(result?.svg?'最新のYAMLを選択範囲の図面に反映しました':'構成は有効です。描画する範囲を選んでください'):'編集が止まると自動で検証します'}</span></div>{issues.map((issue,n)=><button className="issue" key={n} onClick={()=>jump(issue)}>{issue.line&&<span>{issue.line}行{issue.column?':'+issue.column:''}</span>}<code>{issue.path}</code>{issue.message}</button>)}</section>
    <footer><span>LayerMap <b>·</b> 構成の意味を、ひとつに。</span><span>YAMLは描画のためサーバーへ送信されます。永続保存はしません。</span></footer>
    {helpOpen&&<Help limits={limits} samples={samples} loading={sampleLoading} error={sampleError} onClose={()=>setHelpOpen(false)} onLoadSample={loadSample}/>}
    {notice&&<div className="toast" role="status" onClick={()=>setNotice('')}>{notice}<button aria-label="通知を閉じる" onClick={()=>setNotice('')}>×</button></div>}
  </div>;
}

createRoot(document.getElementById('root')!).render(<App/>);
