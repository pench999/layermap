import {test,expect} from '@playwright/test';
async function load(page:any){await page.goto('/');await expect(page.getByLabel('検証結果')).toContainText('検証済み');await page.getByLabel('サンプル構成',{exact:true}).selectOption('subnet-groups');await page.getByRole('button',{name:'サンプルを読み込む',exact:true}).click();await expect(page.locator('.diagram .subnet-display-frame')).toHaveCount(1);await expect(page.getByLabel('検証結果')).toContainText('検証済み');}
const row=(page:any,id:string)=>page.locator('.diagram [data-layer="l3"] .interface-row[data-element-id="'+id+'"]');
test('one display frame retains individual CIDRs, selection, YAML mapping, tracing and exports',async({page})=>{
 await load(page);await page.getByRole('tab',{name:'L3 IP',exact:true}).click();await expect(page.locator('.diagram [data-layer]')).toHaveCount(1);await expect(page.getByLabel('検証結果')).toContainText('検証済み');
 await expect(page.locator('.diagram .network-group[data-network-kind="subnet"]')).toHaveCount(4);
 const group=page.locator('.diagram .subnet-display-group');await group.focus();await page.keyboard.press('Enter');await expect(group).toHaveAttribute('aria-pressed','true');
 await expect(page.getByLabel('図面とYAMLの対応',{exact:true})).toContainText('l3.subnet_groups / service-networks');
 await expect(row(page,'admin.ip')).toHaveCSS('opacity','0.22');await expect(row(page,'app-a.ip')).toHaveCSS('opacity','1');
 await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/subnet-group-selected.png',fullPage:true});
 await page.keyboard.press('Escape');await expect(group).toHaveAttribute('aria-pressed','false');
 const subnet=page.locator('.diagram .network-group[data-network-id="service-b"]');await subnet.focus();await page.keyboard.press('Enter');await expect(page.getByLabel('図面とYAMLの対応',{exact:true})).toContainText('l3.subnets / service-b');
 await row(page,'app-b.ip').focus();await page.keyboard.press('Enter');await expect(page.locator('.diagram [data-layer]')).toHaveCount(3);await expect(page.getByLabel('層間対応の追跡')).toContainText('app-b.eth0');
 const waiting=page.waitForEvent('download');await page.getByRole('button',{name:'YAMLを保存',exact:true}).click();let source='';for await(const c of(await(await waiting).createReadStream())!)source+=c;expect(source).toContain('subnet_groups');expect(source).toContain('2001:db8:100::/64');
});
test('scoping and mobile preserve grouped definitions; hidden invalid references remain errors',async({page,request})=>{
 await load(page);await page.setViewportSize({width:390,height:844});await page.getByLabel('表示する機器',{exact:true}).selectOption('app-b');await expect(page.locator('.diagram .device-card')).toHaveCount(3);
 await expect(page.locator('.diagram .subnet-display-group')).toHaveAttribute('data-subnet-ids',JSON.stringify(['service-b']));
 await page.locator('.diagram .subnet-display-group').focus();await page.keyboard.press('Enter');await expect(page.getByLabel('図面とYAMLの対応',{exact:true})).toContainText('l3.subnet_groups / service-networks');
 await page.getByLabel('表示する機器',{exact:true}).selectOption('admin');await expect(page.locator('.diagram .subnet-display-group')).toHaveCount(0);
 const source=(await(await request.get('/api/samples/subnet-groups')).json()).yaml_text;
 await page.getByRole('textbox',{name:'YAMLエディター'}).fill(source.replace('"members":["service-a","service-b","service-v6"]','"members":["missing"]'));
 await expect(page.getByLabel('検証結果')).toContainText('参照先');
});
