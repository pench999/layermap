import {test,expect} from '@playwright/test';
import {traceGraph,endpointKey,type Graph,type Endpoint} from '../src/trace';
const node=(layer:Endpoint['layer'],id:string)=>({layer,id,device:'gw'});
const a=node('l1','gw.lan'),b=node('l2','gw.trunk'),c=node('l3','gw.v10'),d=node('l3','gw.v20');
const graph:Graph={nodes:[a,b,c,d,node('l1','other')],edges:[
 {key:'one',label:'VLAN 10',source:c,target:b},
 {key:'two',label:'VLAN 20',source:d,target:b},
 {key:'three',label:'physical mapping',source:b,target:a}
]};
test('binding graph fans out from a physical port and walks upstream and downstream',()=>{
 const result=traceGraph(graph,a)!;
 expect(result.nodes).toHaveLength(4);expect(result.edges).toHaveLength(3);
 expect(result.nodes.find(n=>n.id==='gw.trunk')!.degree).toBe(3);
 expect(result.nodes.find(n=>n.id==='gw.v20')!.depth).toBe(2);
 const reverse=traceGraph(graph,c)!;
 expect(reverse.nodes.map(n=>n.id)).toEqual(result.nodes.map(n=>n.id));
 expect(reverse.nodes.find(n=>n.id==='gw.v20')!.depth).toBe(2);
});
test('isolated and missing ports remain isolated rather than selecting their device',()=>{
 expect(traceGraph(graph,node('l1','other'))!.nodes).toHaveLength(1);
 expect(traceGraph(graph,node('l1','other'))!.edges).toHaveLength(0);
 expect(traceGraph(graph,node('l1','missing'))).toBeNull();
});
test('layer-qualified keys distinguish identical IDs and safely handle special characters',()=>{
 const id='same \" [<&]';const lower=node('l1',id),upper=node('l2',id),unrelated=node('l3',id);
 expect(endpointKey(lower)).not.toBe(endpointKey(upper));
 const result=traceGraph({nodes:[lower,upper,unrelated],edges:[{key:'x',label:'x',source:upper,target:lower}]},lower)!;
 expect(result.nodes).toHaveLength(2);expect(result.nodes.map(n=>n.layer)).toEqual(['l1','l2']);
});
test('visited nodes prevent loops and invalid graph endpoints are ignored',()=>{
 const result=traceGraph({nodes:[a,b,c],edges:[graph.edges[0],graph.edges[2],{key:'cycle',label:'cycle',source:a,target:c},{key:'invalid',label:'invalid',source:a,target:d}]},a)!;
 expect(result.nodes).toHaveLength(3);expect(result.edges).toHaveLength(3);
});
