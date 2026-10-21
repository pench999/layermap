export function capacityModel(long=false,extraRow=false){
 const m:any={schema:'lan-example/v1',name:'負荷試験用の架空構成',scope:'合成データ・実機ではありません',devices:[],l1:{ports:[],links:[]},l2:{vlans:[{id:'v10',tag:10}],interfaces:[],bridges:[]},l3:{subnets:[],interfaces:[],routes:[]},bindings:{l2_to_l1:[],l3_to_l2:[]}};
 for(let n=0;n<20;n++){
  const d='d'+String(n).padStart(3,'0'),net='net'+String(n).padStart(3,'0');
  m.devices.push({id:d,name:'Synthetic switch '+String(n).padStart(3,'0'),groups:['rack-'+String(Math.floor(n/8)).padStart(2,'0')],location:{site:'site-00'},manufacturer:'Synthetic',model:'Test-only',serial_number:'FAKE-'+String(n).padStart(6,'0')});
  m.l3.subnets.push({id:net,cidr:'10.0.'+n+'.0/24'});const members=[];
  for(let p=0;p<10;p++){
   const suffix=String(p).padStart(2,'0'),physical=d+'.p'+suffix,l2=d+'.eth'+suffix,l3=d+'.ip'+suffix;
   m.l1.ports.push({id:physical,device:d,name:long?'長い物理ポート名'.repeat(20):'Gi1/0/'+(p+1)});
   m.l2.interfaces.push({id:l2,device:d,mode:'access',untagged_vlan:'v10'});members.push(l2);
   m.l3.interfaces.push({id:l3,device:d,address:'10.0.'+n+'.'+(p+2)+'/24',subnet:net});
   m.bindings.l2_to_l1.push({l2_interface:l2,physical_port:physical});m.bindings.l3_to_l2.push({l3_interface:l3,l2_interface:l2,vlan:'v10'});
  }
  m.l2.bridges.push({id:d+'.bridge',device:d,members});
  if(n%2)m.l1.links.push({id:'cable-'+String(n).padStart(3,'0'),endpoints:['d'+String(n-1).padStart(3,'0')+'.p00',d+'.p00']});
 }
 if(extraRow)m.l1.ports.push({id:'extra-row',device:'d000'});
 if(!long)return m;
 const names=new Map<string,string>();
 const collect=(v:any)=>{if(Array.isArray(v))v.forEach(collect);else if(v&&typeof v==='object'){if(v.id)names.set(v.id,v.id+'-'+'x'.repeat(99-v.id.length));Object.values(v).forEach(collect);}};
 const convert=(v:any):any=>typeof v==='string'?(names.get(v)??v):Array.isArray(v)?v.map(convert):v&&typeof v==='object'?Object.fromEntries(Object.entries(v).map(([k,x])=>[k,convert(x)])):v;
 collect(m);return convert(m);
}
