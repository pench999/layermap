import {test,expect,type Page} from '@playwright/test';
const nav=(page:Page)=>page.getByLabel('図面とYAMLの対応',{exact:true});
const row=(page:Page,layer:string,id:string)=>page.locator('.diagram [data-layer="'+layer+'"] .interface-row[data-element-id="'+id+'"]');
async function download(page:Page){const p=page.waitForEvent('download');await page.getByRole('button',{name:'YAMLを保存',exact:true}).click();const chunks:Buffer[]=[];for await(const c of (await (await p).createReadStream())!)chunks.push(c);return Buffer.concat(chunks).toString('utf8');}
async function definition(page:Page,text:string){await expect.poll(async()=>(await page.locator('.cm-yaml-definition').allTextContents()).join('\n')).toContain(text);}
async function settled(page:Page,text:string){await expect(nav(page)).toContainText(text);await expect(nav(page).getByRole('button',{name:'定義へ',exact:true})).toBeVisible();}
test.beforeEach(async({page})=>{await page.goto('/');await expect(page.getByLabel('検証結果')).toContainText('検証済み');});

test('port definition and related references navigate without editing or stealing focus',async({page})=>{
 const source=await download(page);const port=row(page,'l1','pc-a.eth0');await port.focus();await page.keyboard.press('Enter');await settled(page,'l1.ports / pc-a.eth0');await expect(port).toBeFocused();await definition(page,'pc-a.eth0');expect(await page.locator('.cm-yaml-reference').count()).toBeGreaterThan(0);
 await nav(page).getByRole('button',{name:'YAMLの次の箇所'}).click();await expect(nav(page)).toContainText('2 /');await nav(page).getByRole('button',{name:'定義へ',exact:true}).click();await expect(nav(page)).toContainText('1 /');await definition(page,'pc-a.eth0');expect(await download(page)).toBe(source);
 await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/yaml-source-port.png',fullPage:true});await page.getByRole('button',{name:'YAMLの強調を解除',exact:true}).click();await expect(page.locator('.cm-yaml-definition,.cm-yaml-reference')).toHaveCount(0);
});

test('equipment, cable, VLAN, subnet and mapping use semantic definitions',async({page})=>{
 await page.locator('.diagram [data-device-layer="l1"][data-device="sw01"]').focus();await page.keyboard.press('Enter');await settled(page,'devices / sw01');await definition(page,'HQ-SW-01');
 await page.locator('.diagram [data-cable-id="cable-a"]').focus();await page.keyboard.press('Enter');await settled(page,'l1.links / cable-a');await definition(page,'endpoints');
 await page.locator('.diagram .network-group[data-network-kind="vlan"][data-network-id="vlan-office"]').focus();await page.keyboard.press('Enter');await settled(page,'l2.vlans / vlan-office');await definition(page,'tag: 10');
 await page.locator('.diagram .network-group[data-network-kind="subnet"][data-network-id="net-office"]').focus();await page.keyboard.press('Enter');await settled(page,'l3.subnets / net-office');await definition(page,'192.168.10.0/24');
 const edge=page.locator('.diagram .binding-group').filter({has:page.locator('.binding-edge[data-from="gw01.v20"]')});await edge.focus();await page.keyboard.press('Enter');await settled(page,'bindings.l3_to_l2');await definition(page,'gw01.v20');await definition(page,'vlan-guest');
 await page.keyboard.press('Escape');await expect(page.locator('.cm-yaml-definition')).toHaveCount(0);
});

test('single-layer trace restoration and scoped mapping numbers locate the original YAML',async({page})=>{
 await page.getByRole('tab',{name:'L1 物理',exact:true}).click();await expect(page.locator('.diagram [data-layer]')).toHaveCount(1);await row(page,'l1','gw01.lan').focus();await page.keyboard.press('Space');await settled(page,'l1.ports / gw01.lan');await expect(page.locator('.diagram [data-layer]')).toHaveCount(3);
 await page.getByRole('button',{name:'絞り込みを解除',exact:true}).click();await page.getByLabel('表示する機器',{exact:true}).selectOption('gw01');await expect(page.locator('.diagram .device-card')).toHaveCount(3);
 const edge=page.locator('.diagram .binding-group').filter({has:page.locator('.binding-edge[data-from="gw01.v20"]')});await edge.focus();await page.keyboard.press('Enter');await settled(page,'bindings.l3_to_l2');await definition(page,'gw01.v20');await expect(nav(page)).toContainText('bindings.l3_to_l2[3]');
});

test('editing invalidates ranges immediately and old diagrams and late responses cannot restore them',async({page,request})=>{
 const source=(await (await request.get('/api/sample')).json()).yaml_text;let release!:()=>void,entered!:()=>void;const gate=new Promise<void>(r=>release=r),arrival=new Promise<void>(r=>entered=r);let first=true;
 await page.route('**/api/source/locate',async route=>{if(!first){await route.continue();return;}first=false;const response=await route.fetch();entered();await gate;await route.fulfill({response}).catch(()=>{});});
 await row(page,'l1','pc-a.eth0').focus();await page.keyboard.press('Enter');await arrival;const editor=page.getByRole('textbox',{name:'YAMLエディター'});await editor.fill('bad: [');await expect(page.getByLabel('検証結果')).toContainText('入力を確認');release();await page.unroute('**/api/source/locate');await expect(page.locator('.cm-yaml-definition,.cm-yaml-reference')).toHaveCount(0);
 await row(page,'l1','pc-a.eth0').dispatchEvent('click');await expect(nav(page)).toContainText('停止');await expect(page.locator('.cm-yaml-definition')).toHaveCount(0);
 await editor.fill('# 😀added lines\n\n'+source);await expect(page.getByLabel('検証結果')).toContainText('検証済み');await row(page,'l1','pc-a.eth0').focus();await page.keyboard.press('Enter');await settled(page,'l1.ports / pc-a.eth0');await definition(page,'pc-a.eth0');
 const expected=(await (await request.post('/api/source/locate',{data:{yaml_text:'# 😀added lines\n\n'+source,target:{section:'l1.ports',id:'pc-a.eth0'}}})).json()).locations[0];await expect(nav(page)).toContainText(expected.line+'行');
 await editor.focus();await page.keyboard.press('Control+Home');await page.keyboard.insertText('# manual edit\n');await expect(page.locator('.cm-yaml-definition')).toHaveCount(0);await page.keyboard.press('Control+z');await expect(editor).toContainText('added lines');await expect(editor).not.toContainText('manual edit');
});

test('VPN and Wi-Fi definitions, raw CRLF and mobile navigation are supported',async({page,request})=>{
 const s=await (await request.get('/api/vpn/sample')).json();const p=await (await request.post('/api/vpn/preview',{data:s})).json();await page.locator('input[type=file]').setInputFiles({name:'vpn.yaml',mimeType:'application/yaml',buffer:Buffer.from(p.yaml_text.replaceAll('\n','\r\n'))});await expect(page.locator('.diagram .vpn-group')).toHaveCount(2);await page.locator('.diagram .vpn-group[data-vpn-id="vpn-management"]').focus();await page.keyboard.press('Enter');await settled(page,'vpn_connections / vpn-management');await definition(page,'policy_based');
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'YAMLの定義へ',exact:true}).click();await expect(nav(page)).toBeInViewport();await definition(page,'vpn-management');await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/yaml-source-mobile.png',fullPage:true});expect(await page.locator('.editor-panel').evaluate(e=>e.scrollWidth<=e.clientWidth)).toBe(true);
 await page.getByRole('button',{name:'YAMLを保存',exact:true}).click();await page.getByLabel('サンプル構成').selectOption('connection-status');await page.getByRole('button',{name:'サンプルを読み込む',exact:true}).click();await expect(page.locator('.diagram .l1-connection')).not.toHaveCount(0);const connection=page.locator('.diagram .l1-connection').first();const id=await connection.getAttribute('data-connection-id');await connection.focus();await page.keyboard.press('Enter');await settled(page,'l1.connections / '+id);await definition(page,id!);
 await page.getByRole('button',{name:'ヘルプ',exact:true}).click();await page.getByRole('button',{name:'図面とYAMLの対応',exact:true}).click();await expect(page.locator('#help-source')).toContainText('古い位置を強調しません');
});

test('folded definitions open without moving the cursor and rapid selections discard late results',async({page,request})=>{
 const source=(await (await request.get('/api/sample')).json()).yaml_text;const editor=page.getByRole('textbox',{name:'YAMLエディター'});await editor.focus();await page.keyboard.press('Control+Home');
 for(let n=0;n<source.split('\n').findIndex((line:string)=>line==='devices:');n++)await page.keyboard.press('ArrowDown');
 await page.locator('.cm-foldGutter .cm-gutterElement').filter({hasText:'⌄'}).first().click();await expect(page.locator('.cm-foldPlaceholder')).toHaveCount(1);
 await page.locator('.diagram [data-device-layer="l1"][data-device="sw01"]').focus();await page.keyboard.press('Enter');await settled(page,'devices / sw01');await definition(page,'HQ-SW-01');await expect(page.locator('.cm-foldPlaceholder')).toHaveCount(0);await expect(page.locator('.cm-activeLine')).toHaveText('devices:');
 let release!:()=>void,entered!:()=>void;const gate=new Promise<void>(r=>release=r),arrival=new Promise<void>(r=>entered=r);let first=true;
 await page.route('**/api/source/locate',async route=>{if(!first){await route.continue();return;}first=false;const response=await route.fetch();entered();await gate;await route.fulfill({response}).catch(()=>{});});
 await row(page,'l1','pc-a.eth0').focus();await page.keyboard.press('Enter');await arrival;await row(page,'l1','pc-b.eth0').focus();await page.keyboard.press('Enter');await settled(page,'l1.ports / pc-b.eth0');release();await page.unroute('**/api/source/locate');await settled(page,'l1.ports / pc-b.eth0');await definition(page,'pc-b.eth0');
});

test('automatic YAML navigation keeps the mobile diagram visible even with a late response',async({page})=>{
 await page.setViewportSize({width:390,height:844});let release!:()=>void,entered!:()=>void;const gate=new Promise<void>(r=>release=r),arrival=new Promise<void>(r=>entered=r);let first=true;
 await page.route('**/api/source/locate',async route=>{if(!first){await route.continue();return;}first=false;const response=await route.fetch();entered();await gate;await route.fulfill({response}).catch(()=>{});});
 const port=row(page,'l2','gw01.trunk');await port.focus();await page.keyboard.press('Enter');await arrival;const panel=page.getByLabel('層間対応の追跡');await panel.getByRole('button',{name:/^gw01.v10 /}).click();await expect(row(page,'l3','gw01.v10')).toBeInViewport();const before=await page.evaluate(()=>({y:scrollY,active:document.activeElement?.tagName,focused:!!document.querySelector('.cm-focused'),pane:document.querySelector('.viewport')?.getBoundingClientRect().toJSON(),nav:document.querySelector('.yaml-source-nav')?.getBoundingClientRect().toJSON()}));release();await page.unroute('**/api/source/locate');await settled(page,'l2.interfaces / gw01.trunk');try{await expect(row(page,'l3','gw01.v10')).toBeInViewport();}catch(error){console.log('late YAML viewport',{before,after:await page.evaluate(()=>({y:scrollY,active:document.activeElement?.tagName,focused:!!document.querySelector('.cm-focused'),pane:document.querySelector('.viewport')?.getBoundingClientRect().toJSON(),nav:document.querySelector('.yaml-source-nav')?.getBoundingClientRect().toJSON()}))});throw error;}await page.getByRole('button',{name:'YAMLの定義へ',exact:true}).click();await expect(nav(page)).toBeInViewport();
});
