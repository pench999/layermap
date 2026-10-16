export type Layer = 'l1'|'l2'|'l3';
export type Endpoint = {layer:Layer;id:string};
export type GraphNode = Endpoint & {device:string};
export type GraphEdge = {key:string;label:string;source:Endpoint;target:Endpoint};
export type Graph = {nodes:GraphNode[];edges:GraphEdge[]};
export type Trace = {root:Endpoint;nodes:(GraphNode & {depth:number;degree:number})[];edges:GraphEdge[]};
export const endpointKey = (node:Endpoint) => JSON.stringify([node.layer,node.id]);
const isLayer = (value:string|null):value is Layer => value==='l1'||value==='l2'||value==='l3';

// A row is identified by BOTH layer and ID. Never follow VLAN, subnet or cable
// relationships: this graph contains only the explicit cross-layer bindings.
export function traceGraph(graph:Graph, root:Endpoint):Trace|null {
  const nodes=new Map(graph.nodes.map(node=>[endpointKey(node),node]));
  const rootKey=endpointKey(root);
  if(!nodes.has(rootKey))return null;
  const adjacency=new Map<string,{edge:GraphEdge;next:string}[]>();
  for(const edge of graph.edges){
    const a=endpointKey(edge.source),b=endpointKey(edge.target);
    if(!nodes.has(a)||!nodes.has(b))continue;
    for(const [from,to] of [[a,b],[b,a]]){
      const entries=adjacency.get(from)??[];
      entries.push({edge,next:to});adjacency.set(from,entries);
    }
  }
  const depth=new Map([[rootKey,0]]),queue=[rootKey],edges=new Set<string>();
  for(let index=0;index<queue.length;index++){
    const key=queue[index];
    for(const entry of adjacency.get(key)??[]){
      edges.add(entry.edge.key);
      if(!depth.has(entry.next)){depth.set(entry.next,depth.get(key)!+1);queue.push(entry.next);}
    }
  }
  return {root,nodes:graph.nodes.filter(n=>depth.has(endpointKey(n))).map(n=>({...n,depth:depth.get(endpointKey(n))!,degree:adjacency.get(endpointKey(n))?.length??0})).sort((a,b)=>a.layer.localeCompare(b.layer)),edges:graph.edges.filter(e=>edges.has(e.key))};
}

export function traceFromSvg(svg:string,root:Endpoint):Trace|null {
  const document=new DOMParser().parseFromString(svg,'image/svg+xml');
  const nodes:GraphNode[]=[],edges:GraphEdge[]=[];
  for(const row of document.querySelectorAll('.interface-row')){
    const layer=row.closest('[data-layer]')?.getAttribute('data-layer')??null;
    const id=row.getAttribute('data-element-id');
    if(isLayer(layer)&&id!==null)nodes.push({layer,id,device:row.getAttribute('data-owner')??''});
  }
  for(const group of document.querySelectorAll('.binding-group')){
    const edge=group.querySelector('.binding-edge');
    const upper=edge?.getAttribute('data-from-layer')??null,lower=edge?.getAttribute('data-to-layer')??null;
    const source=edge?.getAttribute('data-from'),target=edge?.getAttribute('data-to');
    const key=group.getAttribute('data-binding-key');
    if(isLayer(upper)&&isLayer(lower)&&source!=null&&target!=null&&key!==null)
      edges.push({key,label:group.getAttribute('aria-label')??key,source:{layer:upper,id:source},target:{layer:lower,id:target}});
  }
  return traceGraph({nodes,edges},root);
}
