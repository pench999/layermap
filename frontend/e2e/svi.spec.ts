import {test,expect,type Page} from '@playwright/test';
const row=(page:Page,layer:string,id:string)=>page.locator('[data-layer="'+layer+'"] .interface-row[data-element-id="'+id+'"]');
async function download(page:Page){const promise=page.waitForEvent('download');await page.getByRole('button',{name:'YAMLを保存',exact:true}).click();let text='';for await(const chunk of (await (await promise).createReadStream())!)text+=chunk;return text;}
async function sample(page:Page){await page.getByLabel('サンプル構成').selectOption('management-svi');await page.getByRole('button',{name:'サンプルを読み込む',exact:true}).click();await expect(page.getByLabel('検証結果')).toContainText('3 VLAN');}
test.beforeEach(async({page})=>{await page.goto('/');await expect(page.getByLabel('検証結果')).toContainText('検証済み');});

test('SVI sample traces only the logical endpoint and IP, including focused and single-layer views',async({page})=>{
 await sample(page);await expect(row(page,'l2','sw01.svi99')).toHaveAttribute('data-interface-mode','svi');await expect(row(page,'l2','sw01.svi99')).toContainText('VLAN 99');await expect(row(page,'l2','sw01.svi99')).toContainText('物理ポートなし');await expect(row(page,'l3','sw01.management')).toContainText('192.168.99.2/24');await expect(row(page,'l3','sw01.management')).toContainText('SVI / VLAN 99');
 await row(page,'l2','sw01.svi99').click();await expect(page.locator('.trace-row')).toHaveCount(2);await expect(page.locator('[data-layer="l1"] .trace-row')).toHaveCount(0);await expect(page.getByLabel('層間対応の追跡')).toContainText('2行・1対応');
 await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/svi-trace.png',fullPage:true});
 await page.getByRole('button',{name:'この対応だけを表示',exact:true}).click();await expect(page.getByLabel('検証結果')).toContainText('検証済み');await expect(page.locator('.interface-row')).toHaveCount(2);await expect(page.locator('[data-layer="l1"] .interface-row')).toHaveCount(0);await expect(row(page,'l3','sw01.management')).toHaveCount(1);expect(await download(page)).toContain('sw01.p24');
 await page.getByRole('button',{name:'絞り込みを解除',exact:true}).click();await expect(page.locator('[data-layer="l1"] .interface-row')).toHaveCount(6);
 for(const label of ['L2 VLAN','L3 IP','L1 物理']){await page.getByRole('tab',{name:label,exact:true}).click();await expect(page.locator('[data-layer]')).toHaveCount(1);await expect(page.getByLabel('検証結果')).toContainText('検証済み');}
 await expect(page.locator('.interface-row[data-element-id="sw01.svi99"]')).toHaveCount(0);
});

async function wizard(page:Page,id:string,attachment='svi'){
 await page.getByRole('button',{name:'機器を追加',exact:true}).click();const d=page.getByRole('dialog',{name:'機器追加ウィザード'});await d.getByLabel('機器の種類').selectOption('l2-switch');await d.getByLabel('機器ID').fill(id);await d.getByLabel('機器名',{exact:true}).fill('管理スイッチ');await d.getByRole('button',{name:'次へ',exact:true}).click();await d.getByLabel('追加するポート数').fill('2');await d.getByRole('button',{name:'次へ',exact:true}).click();await d.getByLabel('VLAN 10 · vlan-office').check();await expect(d.getByLabel('IPの対応先')).toHaveValue('svi');await d.getByLabel('IPの対応先').selectOption(attachment);await d.getByLabel('IPアドレス / プレフィックス').fill(attachment==='svi'?'192.168.20.50/24':'192.168.10.50/24');await d.getByLabel('所属サブネット').selectOption(attachment==='svi'?'net-guest':'net-office');await d.getByLabel('IPに対応するVLAN').selectOption(attachment==='svi'?'vlan-guest':'vlan-office');await d.getByRole('button',{name:'変更内容を確認',exact:true}).click();await expect(d.getByRole('heading',{name:'変更内容の確認'})).toBeVisible();return d;
}

test('wizard creates management SVI on a VLAN independent of physical ports and undo preserves comments',async({page})=>{
 await page.getByRole('textbox',{name:'YAMLエディター'}).focus();await page.keyboard.press('Control+Home');await page.keyboard.insertText('# 管理情報の手動コメント\n');await expect(page.getByLabel('検証結果')).toContainText('検証済み');const before=await download(page);
 const d=await wizard(page,'managed-sw');await expect(d.locator('.input-diff')).toContainText('"mode": "svi"');await expect(d.locator('.input-diff')).toContainText('managed-sw.svi');await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/svi-wizard-review.png',fullPage:true});await d.getByRole('button',{name:'YAMLに適用'}).click();await expect(page.getByLabel('検証結果')).toContainText('5 機器');await expect(row(page,'l2','managed-sw.svi')).toContainText('VLAN 20');await expect(row(page,'l2','managed-sw.p1.l2')).toContainText('VLAN 10');await expect(page.locator('[data-layer="l1"] .interface-row')).toHaveCount(8);await expect(row(page,'l3','managed-sw.ip')).toContainText('SVI / VLAN 20');
 await row(page,'l3','managed-sw.ip').click();await expect(page.locator('.trace-row')).toHaveCount(2);await expect(page.locator('[data-layer="l1"] .trace-row')).toHaveCount(0);
 await page.getByRole('button',{name:'直前のフォーム操作を取り消す'}).click();await expect(page.getByLabel('検証結果')).toContainText('4 機器');expect(await download(page)).toBe(before);
});

test('legacy physical attachment remains selectable for switch IP',async({page})=>{
 const d=await wizard(page,'physical-sw','port');await expect(d.locator('.input-diff')).not.toContainText('"mode": "svi"');await d.getByRole('button',{name:'YAMLに適用'}).click();await expect(page.getByLabel('検証結果')).toContainText('5 機器');await row(page,'l3','physical-sw.ip').click();await expect(page.locator('.trace-row')).toHaveCount(3);await expect(page.locator('[data-layer="l1"] .trace-row')).toHaveCount(1);
});

test('SVI guide, mobile selection and SVG export remain usable',async({page})=>{
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'ヘルプ',exact:true}).click();const help=page.getByRole('dialog',{name:'YAMLの書き方と構成の追加'});await help.getByRole('button',{name:'管理SVI',exact:true}).click();await expect(help.locator('#help-svi')).toContainText('VLAN間ルーティング');await help.getByRole('button',{name:'L2スイッチの管理SVIを読み込む',exact:true}).click();await expect(help).toHaveCount(0);await expect(page.getByLabel('検証結果')).toContainText('3 VLAN');await page.getByRole('tab',{name:'L2 VLAN',exact:true}).click();await expect(row(page,'l2','sw01.svi99')).toHaveCount(1);await row(page,'l2','sw01.svi99').focus();await page.keyboard.press('Enter');await expect(page.locator('.trace-row')).toHaveCount(2);
 const waiting=page.waitForEvent('download');await page.getByRole('button',{name:'SVGを書き出す'}).click();let svg='';for await(const c of (await (await waiting).createReadStream())!)svg+=c;expect(svg).toContain('SVI / 論理VLAN IF・物理ポートなし');expect(svg).toContain('192.168.99.2/24');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/svi-mobile.png',fullPage:true});
});
