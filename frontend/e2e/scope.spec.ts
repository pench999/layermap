import {writeFile} from 'node:fs/promises';
import {test,expect} from '@playwright/test';
function inventory(count=64,ports=2,dense=false){
 const vlans=dense?Array.from({length:64},(_,i)=>({id:'v'+(i+10),tag:i+10})):[{id:'v10',tag:10}];
 const model:any={schema:'lan-example/v1',name:'Synthetic inventory',devices:[],l1:{ports:[],links:[]},l2:{vlans,interfaces:[],bridges:[]},l3:{subnets:[],interfaces:[]},bindings:{l2_to_l1:[],l3_to_l2:[]}};
 for(let n=0;n<count;n++){
  const id='d'+n.toString().padStart(3,'0');
  model.devices.push({id,name:'Device '+n,groups:['group-'+Math.floor(n/4)],location:{site:'site-'+Math.floor(n/16)}});
  model.l3.subnets.push({id:'net'+n,cidr:'10.0.'+n+'.0/24'});const members=[];
  for(let p=0;p<ports;p++){
   const base=id+'.'+p;model.l1.ports.push({id:base,device:id,name:'Port '+p});
   model.l2.interfaces.push({id:base,device:id,mode:dense?'trunk':'access',...(dense?{tagged_vlans:vlans.map(v=>v.id)}:{untagged_vlan:'v10'})});
   model.l3.interfaces.push({id:base,device:id,address:'10.0.'+n+'.'+(p+2)+'/24',subnet:'net'+n});
   model.bindings.l2_to_l1.push({l2_interface:base,physical_port:base});model.bindings.l3_to_l2.push({l3_interface:base,l2_interface:base,vlan:'v10'});members.push(base);
  }
  model.l2.bridges.push({id:id+'.bridge',device:id,members});
  if(n%2===1)model.l1.links.push({id:'cable-'+n,endpoints:['d'+(n-1).toString().padStart(3,'0')+'.0',id+'.0']});
 }
 return model;
}
async function upload(page:any,model:any,padding=0){await page.locator('input[type=file]').setInputFiles({name:'large.yaml',mimeType:'application/yaml',buffer:Buffer.from(JSON.stringify(model)+'\n#'+'x'.repeat(padding))});await expect(page.getByLabel('検証結果')).toContainText('検証済み');}
test.beforeEach(async({page})=>{await page.goto('/');await expect(page.getByLabel('検証結果')).toContainText('検証済み');});

test('whole inventory is retained while site, group and device scopes intersect',async({page})=>{
 const model=inventory();await upload(page,model);
 await expect(page.getByLabel('表示範囲の案内')).toContainText('表示範囲を絞り込んでください');
 await expect(page.getByLabel('検証結果')).toContainText('64 機器');await expect(page.getByRole('button',{name:'SVGを書き出す'})).toBeDisabled();
 await page.getByLabel('表示する拠点',{exact:true}).selectOption(JSON.stringify('site-0'));
 await expect(page.locator('[data-layer="l1"] .device-card')).toHaveCount(16);
 await page.getByLabel('表示する機器群').selectOption(JSON.stringify('group-0'));
 await expect(page.locator('[data-layer="l1"] .device-card')).toHaveCount(4);
 await page.getByLabel('表示する機器',{exact:true}).selectOption('d000');
 await expect(page.locator('[data-layer="l1"] .device-card')).toHaveCount(1);
 await expect(page.getByLabel('表示範囲')).toContainText('範囲外へつながるケーブル 1本');
 await page.getByText('範囲外へつながるケーブル 1本（図から省略）').click();
 await expect(page.getByLabel('表示範囲')).toContainText('d000.0 ↔ d001.0');
 await expect(page.locator('.physical-cable')).toHaveCount(0);
 const download=page.waitForEvent('download');await page.getByRole('button',{name:'YAMLを保存'}).click();const stream=await(await download).createReadStream();let source='';for await(const chunk of stream!)source+=chunk;
 expect(source).toContain('d063');expect(source).toContain('cable-63');
 const svgDownload=page.waitForEvent('download');await page.getByRole('button',{name:'SVGを書き出す'}).click();const svgStream=await(await svgDownload).createReadStream();let svg='';for await(const chunk of svgStream!)svg+=chunk;
 expect(svg).toContain('表示範囲を絞り込んでいます');expect(svg).toContain('ケーブル1本');expect(svg).not.toContain('Device 63');
 await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/scope-desktop.png',fullPage:true});
 await page.getByRole('button',{name:'絞り込みを解除',exact:true}).click();
 await expect(page.getByLabel('表示範囲の案内')).toBeVisible();await expect(page.getByLabel('検証結果')).toContainText('64 機器');
});

test('dense device can be focused before a diagram exists and restored without editing YAML',async({page})=>{
 await upload(page,inventory(1,7,true));await expect(page.getByLabel('表示範囲の案内')).toBeVisible();
 const focus=page.getByLabel('表示する対応関係');await expect(focus.locator('option')).toHaveCount(22);
 await focus.selectOption(JSON.stringify({layer:'l3',id:'d000.0'}));
 await expect(page.locator('.interface-row')).toHaveCount(3);await expect(page.locator('.trace-row')).toHaveCount(3);
 await expect(page.locator('.trace-root')).toHaveAttribute('data-element-id','d000.0');
 await expect(page.getByLabel('検証結果')).toContainText('1 機器');
 await focus.selectOption('');await expect(page.getByLabel('表示範囲の案内')).toBeVisible();await expect(page.getByLabel('層間対応の追跡')).toHaveCount(0);
});

test('selected trunk correspondence becomes an explicit scope and can be cleared on mobile',async({page})=>{
 await page.setViewportSize({width:390,height:844});
 await page.locator('[data-layer="l2"] [data-element-id="gw01.trunk"]').focus();await page.keyboard.press('Enter');
 await page.getByRole('button',{name:'この対応だけを表示'}).click();
 await expect(page.locator('.interface-row')).toHaveCount(4);await expect(page.locator('.trace-row')).toHaveCount(4);
 await expect(page.getByLabel('表示範囲')).toContainText('表示対象 1台・4行');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
 await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/scope-mobile.png',fullPage:true});
 await page.getByLabel('表示する対応関係').selectOption('');await expect(page.locator('[data-layer="l1"] .device-card')).toHaveCount(4);
});

test('hidden invalid references are rejected even with a narrow view',async({page})=>{
 const model=inventory();await upload(page,model);await page.getByLabel('表示する機器',{exact:true}).selectOption('d000');await expect(page.locator('[data-layer="l1"] .device-card')).toHaveCount(1);
 model.bindings.l2_to_l1.at(-1).physical_port='missing-hidden-port';
 await page.getByRole('textbox',{name:'YAMLエディター'}).fill(JSON.stringify(model));await expect(page.getByLabel('検証結果')).toContainText('入力を確認');await expect(page.getByLabel('検証結果')).toContainText('missing-hidden-port');
 await expect(page.getByRole('button',{name:'SVGを書き出す'})).toBeDisabled();
});

test('input above the former 256 KiB limit is accepted and scope changes discard late responses',async({page})=>{
 await upload(page,inventory(4),300000);await expect(page.getByLabel('検証結果')).toContainText('4 機器');
 await page.route('**/api/render',async route=>{if(route.request().postDataJSON().scope.device_ids[0]==='d000')await new Promise(r=>setTimeout(r,1400));try{await route.continue();}catch{}});
 const started=page.waitForRequest(r=>r.url().endsWith('/api/render')&&r.postDataJSON().scope.device_ids[0]==='d000');
 await page.getByLabel('表示する機器',{exact:true}).selectOption('d000');await started;
 await page.getByLabel('表示する機器',{exact:true}).selectOption('d003');await expect(page.getByTestId('diagram')).toContainText('Device 3');
 await expect(page.locator('[data-layer="l1"] .device-card')).toHaveCount(1);await page.waitForTimeout(1700);await expect(page.getByTestId('diagram')).not.toContainText('Device 0');
});

test('temporary busy responses are retried and obsolete retry jobs are aborted',async({page,request})=>{
 const source=(await(await request.get('/api/sample')).json()).yaml_text;let calls=0;
 await page.route('**/api/render',async route=>{if(route.request().postData()!.includes('BUSY-OLD')){calls++;await route.fulfill({status:429,headers:{'Retry-After':'1'},json:{errors:[{message:'busy'}]}});}else await route.continue();});
 const editor=page.getByRole('textbox',{name:'YAMLエディター'});await editor.fill(source.replace('HQ-PC-01','BUSY-OLD'));
 await expect.poll(()=>calls).toBeGreaterThanOrEqual(2);await expect(page.getByLabel('検証結果')).toContainText('更新待ち');
 await editor.fill(source.replace('HQ-PC-01','BUSY-NEW'));await expect(page.getByTestId('diagram')).toContainText('BUSY-NEW');const stopped=calls;await page.waitForTimeout(1600);expect(calls).toBe(stopped);
});

test('browser load timings for bounded drawings from large inventories',async({page})=>{
 test.setTimeout(120000);const reports=[];
 for(const [name,count,ports,dense,scope] of [
  ['24-devices',24,2,false,{site:null,group:null,device_ids:[],trace_root:null}],
  ['64-vlan-trunk',1,4,true,{site:null,group:null,device_ids:[],trace_root:null}],
  ['256-devices-group',256,7,false,{site:null,group:'group-0',device_ids:[],trace_root:null}]
 ] as const){
  const model=inventory(count,ports,dense);
  if(count===256)for(let n=0;n<143;n++)model.l1.ports.push({id:'extra-'+n,device:'d'+(n%256).toString().padStart(3,'0')});
  const source=JSON.stringify(model);
  for(let repeat=0;repeat<3;repeat++){
   const metrics=await page.evaluate(async({source,scope})=>{
    const start=performance.now();const response=await fetch('/api/render',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({yaml_text:source,scope})});const result=await response.json();const received=performance.now();
    const pane=document.createElement('div');pane.style.width='1200px';pane.innerHTML=result.svg;document.body.append(pane);
    pane.getBoundingClientRect();await new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve())));const painted=performance.now();const nodes=pane.querySelectorAll('*').length;pane.remove();
    return {status:response.status,display:result.display.status,counts:result.display.counts,api_ms:received-start,svg_dom_paint_ms:painted-received,total_ms:painted-start,svg_bytes:new TextEncoder().encode(result.svg).length,dom_nodes:nodes};
   },{source,scope});
   expect(metrics.status).toBe(200);expect(metrics.display).toBe('ready');reports.push({name,repeat,...metrics});
  }
 }
 const largeSource=JSON.stringify(inventory(256,7));
 const parallel=await page.evaluate(async source=>{const start=performance.now();const jobs=await Promise.all([0,1].map(async()=>{const r=await fetch('/api/render',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({yaml_text:source,scope:{group:'group-0'}})});const body=await r.json();return {status:r.status,display:body.display?.status,finished_ms:performance.now()-start};}));return {wall_ms:performance.now()-start,jobs};},largeSource);
 expect(parallel.jobs.every(job=>job.status===200&&job.display==='ready')).toBeTruthy();
 await writeFile((process.env.QA_ARTIFACTS||'test-results')+'/scope-browser-benchmark.json',JSON.stringify({parallel,note:'Chromium in Docker; API + JSON + DOM + double requestAnimationFrame; 3 runs per synthetic case',runs:reports},null,2));
});

test('selected mapping line scopes its entire trunk component and empty intersections remain editable',async({page})=>{
 await page.locator('[data-layer="l3"] .binding-badge[data-binding-key="map-2"]').click();
 await page.getByRole('button',{name:'この対応の関連行だけを表示'}).click();
 await expect(page.locator('.interface-row')).toHaveCount(4);await expect(page.locator('.trace-row')).toHaveCount(4);
 await page.getByRole('button',{name:'絞り込みを解除',exact:true}).click();await expect(page.locator('[data-layer="l1"] .device-card')).toHaveCount(4);
 await upload(page,inventory());await page.getByLabel('表示する拠点',{exact:true}).selectOption(JSON.stringify('site-3'));
 await expect(page.locator('[data-layer="l1"] .device-card')).toHaveCount(16);
 await page.getByLabel('表示する機器群').selectOption(JSON.stringify('group-0'));
 await expect(page.getByLabel('表示範囲の案内')).toContainText('表示対象がありません');
 await expect(page.getByRole('button',{name:'YAMLを保存'})).toBeEnabled();
 await page.getByRole('button',{name:'絞り込みを解除',exact:true}).click();await expect(page.getByLabel('表示範囲の案内')).toContainText('表示範囲を絞り込んでください');
});


test('bundled 36-device sample loads from the screen and demonstrates real site and group filters',async({page})=>{
 await page.getByLabel('サンプル構成').selectOption('multi-site');
 await page.getByRole('button',{name:'サンプルを読み込む',exact:true}).click();
 await expect(page.getByLabel('検証結果')).toContainText('36 機器');
 await expect(page.getByLabel('表示範囲の案内')).toContainText('表示範囲を絞り込んでください');
 await expect(page.getByRole('button',{name:'SVGを書き出す'})).toBeDisabled();
 await page.getByLabel('表示する拠点',{exact:true}).selectOption(JSON.stringify('本社'));
 await expect(page.locator('[data-layer="l1"] .device-card')).toHaveCount(12);
 await expect(page.getByTestId('diagram')).toContainText('HQ-GW-01');
 await expect(page.getByTestId('diagram')).not.toContainText('OSK-GW-01');
 await page.getByLabel('表示する機器群').selectOption(JSON.stringify('業務端末'));
 await expect(page.locator('[data-layer="l1"] .device-card')).toHaveCount(6);
 await expect(page.getByLabel('表示範囲')).toContainText('範囲外へつながるケーブル 6本');
 await expect(page.getByLabel('検証結果')).toContainText('36 機器');
 const scroller=page.locator('.cm-scroller');
 expect(await scroller.evaluate(el=>el.scrollHeight>el.clientHeight)).toBeTruthy();
 await scroller.evaluate(el=>{el.scrollTop=el.scrollHeight;});
 await expect(page.locator('.cm-content')).toContainText('notes:');
 await scroller.evaluate(el=>{el.scrollTop=0;});
 expect(await page.evaluate(()=>document.documentElement.scrollHeight)).toBeLessThan(2400);
 expect(await page.locator('.editor-panel').evaluate(el=>el.getBoundingClientRect().height)).toBeLessThanOrEqual(1000);
 await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/multisite-office.png',fullPage:true});
 await page.getByLabel('表示する機器群').selectOption(JSON.stringify('フロアA'));
 await expect(page.locator('[data-layer="l1"] .device-card')).toHaveCount(6);
 await expect(page.getByTestId('diagram')).toContainText('HQ-SW-01');
 await page.getByLabel('表示する拠点',{exact:true}).selectOption('null');
 await page.getByLabel('表示する機器群').selectOption(JSON.stringify('ネットワーク機器'));
 await expect(page.locator('[data-layer="l1"] .device-card')).toHaveCount(9);
 for(const code of ['HQ','OSK','FUK'])await expect(page.getByTestId('diagram')).toContainText(code+'-GW-01');
 const download=page.waitForEvent('download');await page.getByRole('button',{name:'YAMLを保存'}).click();const yaml=await download;expect(yaml.suggestedFilename()).toBe('03-multi-site-36.yaml');
 const stream=await yaml.createReadStream();let source='';for await(const chunk of stream!)source+=chunk;expect(source).toContain('fuk-pc09');expect(source).toContain('hq-pc01');
 await page.getByRole('button',{name:'絞り込みを解除',exact:true}).click();
 await expect(page.getByLabel('表示範囲の案内')).toBeVisible();
 await page.getByLabel('サンプル構成').selectOption('base');await page.getByRole('button',{name:'サンプルを読み込む',exact:true}).click();await expect(page.getByLabel('検証結果')).toContainText('4 機器');
 await page.getByRole('button',{name:'ヘルプ',exact:true}).click();const help=page.getByRole('dialog');await expect(help).toContainText('拠点「本社」で12台');
 await help.getByRole('button',{name:'複数拠点・機器群（36台）を読み込む',exact:true}).click();await expect(help).toHaveCount(0);await expect(page.getByLabel('検証結果')).toContainText('36 機器');
 await page.getByLabel('表示する拠点',{exact:true}).selectOption(JSON.stringify('大阪支社'));await expect(page.locator('[data-layer="l1"] .device-card')).toHaveCount(12);await expect(page.getByTestId('diagram')).toContainText('OSK-GW-01');
});
