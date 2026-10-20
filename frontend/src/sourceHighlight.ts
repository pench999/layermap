import {useEffect,useRef,useState,type RefObject} from 'react';
import {StateEffect,StateField,Transaction} from '@codemirror/state';
import {Decoration,EditorView,type DecorationSet} from '@codemirror/view';
import {foldedRanges,unfoldEffect} from '@codemirror/language';
import {requestJson} from './InputSupport';
import {normalized} from './sourceEdits';
export type SourceTarget={section:string;id?:string;match?:Record<string,string>};
export type SourceLocation={from:number;to:number;line:number;column:number;path:string;kind:'definition'|'reference'|'related_definition'};
type Report={locations:SourceLocation[];label:string;total:number;limit:number;truncated:boolean};
type Paint={locations:SourceLocation[];current:number};
export const sourcePaint=StateEffect.define<Paint>();
export const sourceMarks=StateField.define<DecorationSet>({
 create:()=>Decoration.none,
 update(value,tr){
  if(tr.docChanged)return Decoration.none;
  for(const e of tr.effects)if(e.is(sourcePaint))return Decoration.set(e.value.locations.filter(r=>r.to>r.from).map((r,i)=>Decoration.mark({class:'cm-yaml-'+(r.kind==='definition'?'definition':'reference')+(i===e.value.current?' cm-yaml-current':''),attributes:{'data-yaml-path':r.path,'data-yaml-kind':r.kind}}).range(r.from,r.to)),true);
  return value;
 },provide:field=>EditorView.decorations.from(field)
});
const sourceMeasures=new WeakMap<EditorView,number>();
const sourceY=Symbol('source-y'),sourceX=Symbol('source-x');
export function targetForElement(element:Element|null,canvas:Element|null):SourceTarget|null{
 if(!element)return null;
 const vpn=element.closest<SVGGElement>('.vpn-group');if(vpn)return {section:'vpn_connections',id:vpn.dataset.vpnId!};
 const binding=element.closest<SVGGElement>('.binding-group,.binding-badge');
 if(binding){const group=Array.from(canvas?.querySelectorAll<SVGGElement>('.binding-group')??[]).find(g=>g.dataset.bindingKey===binding.dataset.bindingKey);const edge=group?.querySelector('.binding-edge');if(!edge)return null;return edge.getAttribute('data-from-layer')==='l3'?{section:'bindings.l3_to_l2',match:{l3_interface:edge.getAttribute('data-from')!,l2_interface:edge.getAttribute('data-to')!}}:{section:'bindings.l2_to_l1',match:{l2_interface:edge.getAttribute('data-from')!,physical_port:edge.getAttribute('data-to')!}};}
 const row=element.closest<SVGGElement>('.interface-row');if(row){const layer=row.closest('[data-layer]')?.getAttribute('data-layer');return {section:layer==='l1'?'l1.ports':layer+'.interfaces',id:row.dataset.elementId!};}
 const cable=element.closest<SVGGElement>('[data-cable-id]');if(cable)return {section:'l1.links',id:cable.dataset.cableId!};
 const connection=element.closest<SVGGElement>('[data-connection-id]');if(connection)return {section:'l1.connections',id:connection.dataset.connectionId!};
 const network=element.closest<SVGGElement>('.network-group');if(network)return {section:({subnet:'l3.subnets',vlan:'l2.vlans',bridge:'l2.bridges'} as Record<string,string>)[network.dataset.networkKind!],id:network.dataset.networkId!};
 const device=element.closest<SVGGElement>('[data-device]');return device?{section:'devices',id:device.dataset.device!}:null;
}
function editorLocations(source:string,locations:SourceLocation[]){
 const offsets=new Map<number,number>();let cursor=0,units=0;
 for(const pos of [...new Set(locations.flatMap(r=>[r.from,r.to]))].sort((a,b)=>a-b)){units+=normalized(source.slice(cursor,pos)).length;cursor=pos;offsets.set(pos,units);}
 return locations.map(r=>({...r,from:offsets.get(r.from)!,to:offsets.get(r.to)!}));
}
export function useSourceHighlight(editor:RefObject<EditorView|null>,source:string,target:SourceTarget|null,enabled:boolean){
 const [report,setReport]=useState<Report|null>(null),[current,setCurrent]=useState(0),[pending,setPending]=useState(false),[error,setError]=useState('');
 const latest=useRef({source,enabled});latest.current={source,enabled};const snapshot=useRef(''),mapped=useRef<SourceLocation[]>([]),sequence=useRef(0);
 const key=JSON.stringify(target);
 const paint=(locations:SourceLocation[],index:number,scroll=false)=>{
  const ed=editor.current;if(!ed)return;const n=(sourceMeasures.get(ed)??0)+1;sourceMeasures.set(ed,n);
  const folds:ReturnType<typeof unfoldEffect.of>[]=[];
  if(scroll&&locations[index])foldedRanges(ed.state).between(locations[index].from,locations[index].to,(from,to)=>{folds.push(unfoldEffect.of({from,to}));});
  ed.dispatch({effects:[...folds,sourcePaint.of({locations,current:index})],annotations:Transaction.addToHistory.of(false)});
  if(!scroll||!locations[index])return;
  const pos=locations[index].from,doc=ed.state.doc;
  const valid=()=>editor.current===ed&&sourceMeasures.get(ed)===n&&ed.state.doc===doc;
  // EditorView.scrollIntoView can move outer pages as well. Measure the
  // target line and adjust only this editor's scroll container.
  ed.requestMeasure({key:sourceY,read:()=>valid()?ed.lineBlockAt(pos):null,write:block=>{
   if(!block||!valid())return;
   ed.scrollDOM.scrollTop=Math.max(0,block.top-(ed.scrollDOM.clientHeight-block.height)/2);
   ed.requestMeasure({key:sourceX,read:()=>valid()?{box:ed.coordsAtPos(pos),frame:ed.scrollDOM.getBoundingClientRect()}:null,write:data=>{
    if(!data?.box||!valid())return;const {box,frame}=data;
    if(box.left<frame.left+48)ed.scrollDOM.scrollLeft+=box.left-frame.left-48;
    else if(box.right>frame.right-24)ed.scrollDOM.scrollLeft+=box.right-frame.right+24;
   }});
  }});
 };

 useEffect(()=>{
  const n=++sequence.current,c=new AbortController();setReport(null);setCurrent(0);setError('');mapped.current=[];paint([],0);
  if(!enabled||!target){setPending(false);return()=>c.abort();}
  setPending(true);
  const timer=setTimeout(async()=>{try{
   const data=await requestJson('/api/source/locate',{yaml_text:source,target},c.signal) as Report;
   const ed=editor.current;if(c.signal.aborted||n!==sequence.current||latest.current.source!==source||!latest.current.enabled||!ed||ed.state.doc.toString()!==normalized(source))return;
   if(!data.locations.every(r=>Number.isInteger(r.from)&&Number.isInteger(r.to)&&r.from>=0&&r.to>=r.from&&r.to<=source.length))throw Error('YAMLの記述位置を取得できません');
   const ranges=editorLocations(source,data.locations);mapped.current=ranges;snapshot.current=source;setReport(data);setCurrent(0);paint(ranges,0,true);
  }catch(e){if(!c.signal.aborted&&n===sequence.current)setError(e instanceof Error?e.message:String(e));}finally{if(n===sequence.current&&!c.signal.aborted)setPending(false);}},80);
  return()=>{clearTimeout(timer);c.abort();};
 },[source,key,enabled]);
 const move=(index:number,reveal=false)=>{const ed=editor.current;if(!report||!latest.current.enabled||snapshot.current!==latest.current.source||!ed||ed.state.doc.toString()!==normalized(snapshot.current))return;const next=(index+report.locations.length)%report.locations.length;setCurrent(next);paint(mapped.current,next,true);if(reveal)(ed.dom.closest('.editor-panel')??ed.dom).scrollIntoView({block:'start',inline:'nearest'});};
 return {report,current,pending,error,move};
}
