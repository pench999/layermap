import {test,expect,type Page} from '@playwright/test';
import {writeFile} from 'node:fs/promises';
import {capacityModel} from './capacityModel';
async function sample(page:Page){await page.getByLabel('サンプル構成',{exact:true}).selectOption('three-48port');await page.getByRole('button',{name:'サンプルを読み込む',exact:true}).click();await expect(page.getByLabel('検証結果')).toContainText('15 機器');await expect(page.locator('.diagram .interface-row')).toHaveCount(414);}
async function upload(page:Page,model:any){await page.locator('input[type=file]').setInputFiles({name:'capacity.yaml',mimeType:'application/yaml',buffer:Buffer.from(JSON.stringify(model))});}
test.beforeEach(async({page})=>{await page.goto('/');await expect(page.getByLabel('検証結果')).toContainText('検証済み');});

test('three 48-port switches render all physical rows, 12 hosts and links',async({page,request})=>{
 await sample(page);const limits=await(await request.get('/api/limits')).json();expect(limits).toMatchObject({view_rows:600,view_connections:1200,view_elements:1600,svg_bytes:8388608,wizard_ports:64});
 await expect(page.locator('.diagram .physical-cable')).toHaveCount(50);
 for(const sw of ['sw01','sw02','sw03']){await expect(page.locator('.diagram [data-layer="l1"] .interface-row[data-owner="'+sw+'"]')).toHaveCount(48);await expect(page.locator('.diagram [data-layer="l2"] .interface-row[data-owner="'+sw+'"]')).toHaveCount(49);}
 await expect(page.getByLabel('表示範囲',{exact:true})).toContainText('414行');await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/48port-all-desktop.png',fullPage:true});
});

test('48th port and SVI remain selectable when scoped and YAML export retains all hosts',async({page})=>{
 await sample(page);await page.getByLabel('表示する機器',{exact:true}).selectOption('sw01');await expect(page.locator('.diagram .interface-row')).toHaveCount(98);
 await expect(page.getByLabel('表示範囲',{exact:true})).toContainText('ケーブル 13本');
 const row=page.locator('.diagram [data-layer="l1"] .interface-row[data-element-id="sw01.p48"]');await row.focus();await page.keyboard.press('Enter');await expect(page.locator('.diagram .trace-row')).toHaveCount(2);await expect(page.getByLabel('図面とYAMLの対応',{exact:true})).toContainText('l1.ports / sw01.p48');
 await page.locator('.diagram [data-layer="l3"] .interface-row[data-element-id="sw01.management"]').focus();await page.keyboard.press('Enter');await expect(page.locator('.diagram .trace-row')).toHaveCount(2);await expect(page.locator('.diagram [data-layer="l1"] .trace-row')).toHaveCount(0);
 const wait=page.waitForEvent('download');await page.getByRole('button',{name:'YAMLを保存',exact:true}).click();const file=await wait;let yaml='';for await(const c of (await file.createReadStream())!)yaml+=c;expect(yaml).toContain('host12');expect(file.suggestedFilename()).toBe('12-three-48port-switches.yaml');
 await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/48port-switch-desktop.png',fullPage:true});
});

test('mobile can select the last port, trace across layers and restore the full view',async({page})=>{
 await page.setViewportSize({width:390,height:844});await sample(page);await page.getByLabel('表示する機器',{exact:true}).selectOption('sw03');await expect(page.locator('.diagram .interface-row')).toHaveCount(98);await page.getByRole('tab',{name:'L1 物理',exact:true}).click();await expect(page.locator('.diagram .interface-row')).toHaveCount(48);
 await page.locator('.diagram .interface-row[data-element-id="sw03.p48"]').focus();await page.keyboard.press('Enter');await expect(page.locator('.diagram .trace-row')).toHaveCount(2);await expect(page.getByLabel('図面とYAMLの対応',{exact:true})).toContainText('sw03.p48');await page.getByRole('button',{name:'YAMLの定義へ',exact:true}).click();await expect(page.locator('.cm-yaml-definition').first()).toBeVisible();await expect(page.locator('.cm-content')).toContainText('sw03.p48');for(let n=0;n<9;n++)await page.getByRole('button',{name:'拡大',exact:true}).click();await page.getByRole('button',{name:/^sw03\.p48（起点）/}).click();await expect(page.locator('.diagram [data-layer="l1"] .interface-row[data-element-id="sw03.p48"]')).toBeInViewport();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/48port-mobile.png',fullPage:false});await page.getByRole('button',{name:'絞り込みを解除',exact:true}).click();await expect(page.locator('.diagram .interface-row')).toHaveCount(414);
});

test('wizard adds a 48-port switch with 4 uplinks without a 24-port form restriction',async({page})=>{
 await sample(page);await page.getByRole('button',{name:'機器を追加',exact:true}).click();const dialog=page.getByRole('dialog',{name:'機器追加ウィザード'});await dialog.getByLabel('機器の種類',{exact:true}).selectOption('l2-switch');await dialog.getByLabel('機器ID（必須・変更しない識別子）',{exact:true}).fill('sw52');await dialog.getByRole('button',{name:'次へ',exact:true}).click();const count=dialog.getByLabel('追加するポート数',{exact:true});await expect(count).toHaveAttribute('max','64');await count.fill('52');await dialog.getByRole('button',{name:'次へ',exact:true}).click();await dialog.getByRole('radio',{name:/VLAN 1 · v1 /}).check();await dialog.getByRole('button',{name:'変更内容を確認',exact:true}).click();await expect(dialog.getByLabel('変更内容の確認')).toContainText('52');await dialog.getByRole('button',{name:'YAMLに適用',exact:true}).click();await expect(page.getByLabel('検証結果')).toContainText('16 機器');await expect(page.locator('.diagram [data-layer="l1"] .interface-row[data-owner="sw52"]')).toHaveCount(52);await expect(page.locator('.diagram .interface-row')).toHaveCount(518);
});

test('600 rows and a SVG above the old 4 MiB cap render; 601 rows remain safely scoped',async({page,request})=>{
 test.setTimeout(90000);await upload(page,capacityModel(true));await expect(page.locator('.diagram .interface-row')).toHaveCount(600);await expect(page.getByLabel('検証結果')).toContainText('検証済み');const exported=page.waitForEvent('download');await page.getByRole('button',{name:'SVGを書き出す'}).click();let svg='';for await(const c of (await(await exported).createReadStream())!)svg+=c;expect(Buffer.byteLength(svg)).toBeGreaterThan(4*1024*1024);expect(Buffer.byteLength(svg)).toBeLessThan(8*1024*1024);
 await page.getByLabel('表示する機器',{exact:true}).selectOption({index:1});await expect(page.locator('.diagram .interface-row')).toHaveCount(30);
 await upload(page,capacityModel(false,true));await expect(page.getByLabel('表示範囲の案内')).toContainText('表示範囲を絞り込んでください');await expect(page.getByRole('button',{name:'SVGを書き出す'})).toBeDisabled();await page.getByLabel('表示する機器',{exact:true}).selectOption('d000');await expect(page.locator('.diagram .interface-row')).toHaveCount(31);await expect(page.getByRole('button',{name:'YAMLを保存',exact:true})).toBeEnabled();
});

test('48-port browser load and interaction timings at normal and boundary sizes',async({page,request})=>{
 test.setTimeout(180000);const source=(await(await request.get('/api/samples/three-48port')).json()).yaml_text;const reports=[];
 for(const [name,text] of [['three-48-switches-12-hosts',source],['rows-600',JSON.stringify(capacityModel())],['rows-600-long-ids-and-labels',JSON.stringify(capacityModel(true))]])for(let repeat=0;repeat<3;repeat++){
  const result=await page.evaluate(async source=>{
   const start=performance.now();const response=await fetch('/api/render',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({yaml_text:source})});const data=await response.json();const received=performance.now();const pane=document.createElement('div');pane.style.cssText='width:1200px;height:800px;overflow:auto;position:fixed;left:0;top:0;background:white;z-index:100';pane.innerHTML=data.svg;document.body.append(pane);pane.getBoundingClientRect();await new Promise<void>(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>r())));const painted=performance.now();
   pane.scrollTop=pane.scrollHeight/2;pane.scrollLeft=pane.scrollWidth/2;const svg=pane.querySelector('svg');if(svg){svg.style.transformOrigin='top left';svg.style.transform='scale(.8)';}await new Promise<void>(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>r())));const moved=performance.now();const nodes=pane.querySelectorAll('*').length;pane.remove();return {status:response.status,display:data.display.status,counts:data.display.counts,api_ms:received-start,svg_dom_paint_ms:painted-received,pan_zoom_ms:moved-painted,total_ms:moved-start,svg_bytes:new TextEncoder().encode(data.svg).length,dom_nodes:nodes};
  },text);expect(result.status).toBe(200);expect(result.display).toBe('ready');reports.push({name,repeat,...result});
 }
 const parallel=await page.evaluate(async source=>{const start=performance.now();const jobs=await Promise.all([0,1].map(async()=>{const response=await fetch('/api/render',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({yaml_text:source})});const data=await response.json();return {status:response.status,display:data.display?.status,ms:performance.now()-start};}));return {wall_ms:performance.now()-start,jobs};},source);expect(parallel.jobs.every(j=>j.status===200&&j.display==='ready')).toBeTruthy();await writeFile((process.env.QA_ARTIFACTS||'test-results')+'/48port-browser-benchmark.json',JSON.stringify({note:'Chromium in Docker; API + JSON + DOM + double animation frames; pan/zoom each; 3 runs; no editor debounce',runs:reports,parallel},null,2));
});
