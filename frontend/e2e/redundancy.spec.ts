import {test,expect,type Page} from '@playwright/test';
const row=(page:Page,layer:string,id:string)=>page.locator('.diagram [data-layer="'+layer+'"] .interface-row[data-element-id="'+id+'"]');
const nav=(page:Page)=>page.getByLabel('図面とYAMLの対応',{exact:true});
async function choose(page:Page,layer:string,id:string){await row(page,layer,id).focus();await page.keyboard.press('Enter');await expect(page.getByLabel('層間対応の追跡')).toContainText(id);}
test.beforeEach(async({page})=>{await page.goto('/');await expect(page.getByLabel('検証結果')).toContainText('検証済み');await page.getByLabel('サンプル構成',{exact:true}).selectOption('aggregation-stack-mlag');await page.getByRole('button',{name:'サンプルを読み込む',exact:true}).click();await expect(page.getByLabel('検証結果')).toContainText('8 機器');});

test('physical chassis stay separate while stack and aggregate rows track all members',async({page})=>{
 await expect(page.locator('.diagram [data-device-layer="l1"]')).toHaveCount(7);await expect(page.locator('.diagram [data-device-layer="l1"][data-device="stack01"]')).toHaveCount(0);for(const layer of ['l2','l3']){await expect(page.locator('.diagram [data-device-layer="'+layer+'"][data-device="stack01"]')).toHaveCount(1);await expect(page.locator('.diagram [data-device-layer="'+layer+'"][data-device="sw1"]')).toHaveCount(0);}
 await expect(page.getByTestId('diagram')).toContainText('DEMO-SN-4');await expect(page.getByTestId('diagram')).toContainText('DEMO-SN-5');await expect(page.locator('.diagram .physical-cable')).toHaveCount(9);
 await choose(page,'l3','srv-bond.ip10');await expect(page.locator('.diagram .trace-row')).toHaveCount(5);for(const id of ['srv-bond.eth0','srv-bond.eth1'])await expect(row(page,'l1',id)).toHaveClass(/trace-row/);await expect(row(page,'l3','srv-bond.ip20')).toHaveClass(/trace-row/);await expect(row(page,'l2','stack01.po1')).not.toHaveClass(/trace-row/);
 await choose(page,'l2','stack01.po1');await expect(page.locator('.diagram .trace-row')).toHaveCount(3);for(const id of ['sw1.p1','sw2.p1'])await expect(row(page,'l1',id)).toHaveClass(/trace-row/);
 await expect(nav(page)).toContainText('l2.interfaces / stack01.po1');await expect(page.locator('.cm-yaml-definition')).not.toHaveCount(0);
 await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/aggregation-stack-desktop.png',fullPage:true});
});

test('stack selection and physical filter preserve both chassis and logical definition',async({page})=>{
 await page.getByLabel('機器の強調表示').selectOption('stack01');await expect(page.locator('.diagram .selected-device')).toHaveCount(4);
 await page.getByLabel('表示する機器',{exact:true}).selectOption('sw1');await expect(page.getByLabel('表示範囲',{exact:true})).toContainText('表示対象 3台');await expect(page.locator('.diagram [data-device-layer="l1"]')).toHaveCount(2);await expect(page.getByTestId('diagram')).toContainText('STACKの物理メンバー');
 const edge=page.locator('.diagram .binding-group').filter({has:page.locator('.binding-edge[data-from="stack01.po1"][data-to="sw2.p1"]')});await edge.focus();await page.keyboard.press('Enter');await expect(nav(page)).toContainText('bindings.l2_to_l1[3]');await expect(page.locator('.cm-yaml-definition')).toContainText('sw2.p1');
 await page.getByRole('button',{name:'この対応の関連行だけを表示',exact:true}).click();await expect(page.locator('.diagram .interface-row')).toHaveCount(3);await expect(row(page,'l1','sw2.p1')).toHaveCount(1);await expect(page.getByLabel('検証結果')).toContainText('検証済み');
});

test('MLAG peers retain independent cards and source definitions; a partial peer scope is explicit',async({page})=>{
 for(const layer of ['l1','l2','l3'])for(const device of ['leaf1','leaf2'])await expect(page.locator('.diagram [data-device-layer="'+layer+'"][data-device="'+device+'"]')).toHaveCount(1);
 const domain=page.locator('.diagram .equipment-domain').first();await domain.focus();await page.keyboard.press('Enter');await expect(nav(page)).toContainText('mlag_domains / mlag01');await expect(page.locator('.diagram .domain-selected')).toHaveCount(6);await expect(page.locator('.cm-yaml-definition')).toContainText('interface_pairs');
 await choose(page,'l2','leaf1.po11');await expect(row(page,'l1','leaf1.p1')).toHaveClass(/trace-row/);await expect(row(page,'l2','leaf2.po11')).not.toHaveClass(/trace-row/);
 await page.getByLabel('表示する機器',{exact:true}).selectOption('leaf1');await expect(page.locator('.diagram .equipment-domain')).toHaveCount(0);await expect(page.getByTestId('diagram')).toContainText('範囲外のpeer');await expect(row(page,'l2','leaf1.po11')).toHaveCount(1);await expect(page.getByLabel('検証結果')).toContainText('検証済み');
});

test('hidden MLAG mismatch blocks rendering and saved YAML keeps physical and logical references',async({page,request})=>{
 const sample=(await (await request.get('/api/samples/aggregation-stack-mlag')).json()).yaml_text;await page.getByLabel('表示する機器',{exact:true}).selectOption('srv-bond');await expect(page.locator('.diagram [data-device]')).toHaveCount(3);
 const before='"id":"leaf2.po11","device":"leaf2","mode":"access","untagged_vlan":"v10"';expect(sample).toContain(before);await page.getByRole('textbox',{name:'YAMLエディター'}).fill(sample.replace(before,before.replace('v10','v20')));await expect(page.getByLabel('検証結果')).toContainText('MLAGペア');await expect(page.getByRole('button',{name:'SVGを書き出す'})).toBeDisabled();
 await page.getByRole('textbox',{name:'YAMLエディター'}).fill(sample);await expect(page.getByLabel('検証結果')).toContainText('検証済み');const waiting=page.waitForEvent('download');await page.getByRole('button',{name:'YAMLを保存',exact:true}).click();const downloaded=await waiting;let source='';for await(const c of (await downloaded.createReadStream())!)source+=c;expect(source).toBe(sample);expect(downloaded.suggestedFilename()).toBe('11-aggregation-stack-mlag.yaml');
});

test('mobile team member tracing and help explain aggregation versus stack and MLAG',async({page})=>{
 await page.setViewportSize({width:390,height:844});await page.getByLabel('表示する機器',{exact:true}).selectOption('srv-team');await expect(row(page,'l2','srv-team.team0')).toContainText('active_backup');await choose(page,'l1','srv-team.eth1');await expect(page.locator('.diagram .trace-row')).toHaveCount(4);await expect(row(page,'l1','srv-team.eth0')).toHaveClass(/trace-row/);await expect(nav(page)).toContainText('l1.ports / srv-team.eth1');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/aggregation-team-mobile.png',fullPage:true});
 await page.getByRole('button',{name:'ヘルプ',exact:true}).click();const help=page.getByRole('dialog',{name:'YAMLの書き方と構成の追加'});await help.getByRole('button',{name:'Bond・LAG・STACK・MLAG',exact:true}).click();await expect(help.locator('#help-aggregation')).toContainText('独立');await expect(help.locator('#help-aggregation')).toContainText('primary_port');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});

test('routed aggregate traces IP and physical members without a VLAN',async({page,request})=>{
 let source=(await (await request.get('/api/samples/aggregation-stack-mlag')).json()).yaml_text;
 source=source.replaceAll('"mode":"trunk","tagged_vlans":["v10","v20"]','"mode":"routed"').replace('"members":["stack01.po1","stack01.svi10"]','"members":["stack01.svi10"]');
 source=source.replace(/("l3_interface":"srv-bond\.ip(?:10|20)","l2_interface":"srv-bond.bond0"),"vlan":"v(?:10|20)"/g,'$1');
 await page.getByRole('textbox',{name:'YAMLエディター'}).fill(source);await expect(row(page,'l2','srv-bond.bond0')).toContainText('routed / VLANなし');await expect(page.getByLabel('検証結果')).toContainText('検証済み');await choose(page,'l3','srv-bond.ip10');await expect(page.locator('.diagram .trace-row')).toHaveCount(5);await expect(row(page,'l1','srv-bond.eth1')).toHaveClass(/trace-row/);
});

test('aggregate selected during a pending scope redraw stays selected after the response',async({page})=>{
 let release!:()=>void,arrived!:()=>void;const gate=new Promise<void>(r=>release=r),arrival=new Promise<void>(r=>arrived=r);
 await page.route('**/api/render',async route=>{if(!route.request().postDataJSON().scope?.device_ids?.includes('srv-team')){await route.continue();return;}const response=await route.fetch();arrived();await gate;await route.fulfill({response}).catch(()=>{});});
 await page.getByLabel('表示する機器',{exact:true}).selectOption('srv-team');await arrival;await choose(page,'l2','srv-team.team0');release();await expect(page.getByLabel('検証結果')).toContainText('検証済み');await expect(nav(page)).toContainText('l2.interfaces / srv-team.team0');await expect(page.locator('.diagram .trace-row')).toHaveCount(4);
});
