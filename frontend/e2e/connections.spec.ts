import {test,expect} from '@playwright/test';
test.beforeEach(async({page})=>{await page.goto('/');await expect(page.getByLabel('検証結果')).toContainText('検証済み');await page.getByLabel('サンプル構成').selectOption('connection-status');await page.getByRole('button',{name:'サンプルを読み込む',exact:true}).click();await expect(page.getByLabel('検証結果')).toContainText('10 機器');});

test('wired, Wi-Fi and uncertainty remain distinct in the diagram and SVG export',async({page})=>{
 await page.getByRole('tab',{name:'L1 物理'}).click();await expect(page.locator('[data-layer]')).toHaveCount(1);
 await expect(page.locator('.physical-cable')).toHaveCount(3);await expect(page.locator('.l1-connection')).toHaveCount(6);
 await expect(page.locator('.wifi-wave')).toHaveCount(4);await expect(page.locator('.wired-path')).toHaveCount(2);
 await expect(page.locator('.unresolved-endpoint')).toHaveCount(2);await expect(page.locator('.unknown-peer')).toHaveCount(2);
 await expect(page.locator('[data-layer="l1"] .device-card')).toHaveCount(10);
 const unknown=page.locator('.l1-connection[data-connection-id="wired-port-unknown"]');await expect(unknown).toHaveAttribute('data-connection-status','port_unknown');await expect(unknown.locator('path')).toHaveAttribute('stroke-dasharray','10 3 2 3');
 const wifi=page.locator('.l1-connection[data-connection-id="wifi-confirmed-1"]');await expect(wifi.locator('path')).toHaveAttribute('d',/Q/);await expect(wifi).toHaveAttribute('aria-label',/wifi1.wlan0 ↔ ap01.wlan0/);
 await wifi.focus();await expect(wifi.locator('path')).toHaveCSS('stroke-width','3.5px');
 const ap=page.locator('[data-layer="l1"] [data-element-id="ap01.wlan0"]');await expect(ap).toHaveCount(1);
 await expect(page.getByLabel('検証結果')).toContainText('9 L1接続');
 const downloading=page.waitForEvent('download');await page.getByRole('button',{name:'SVGを書き出す'}).click();const file=await downloading;const stream=await file.createReadStream();let svg='';for await(const chunk of stream!)svg+=chunk;expect(svg).toContain('wifi-wave');expect(svg).toContain('AP未確認');expect(svg).toContain('LayerMap-Office');
 await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/connections-l1.png',fullPage:true});
 await page.getByLabel('表示する機器群').selectOption(JSON.stringify('共有APの確認例'));await expect(page.locator('[data-layer="l1"] .device-card')).toHaveCount(3);await expect(page.locator('.wifi-wave')).toHaveCount(2);await expect(page.locator('[data-element-id="ap01.wlan0"]')).toHaveCount(1);await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/connections-shared-ap.png',fullPage:true});
});

test('unknown AP stays unknown when scoped and known out-of-scope connections keep their status',async({page})=>{
 await page.getByRole('tab',{name:'L1 物理'}).click();await expect(page.locator('[data-layer]')).toHaveCount(1);
 await page.getByLabel('表示する機器',{exact:true}).selectOption('wifi4');await expect(page.locator('[data-layer="l1"] .device-card')).toHaveCount(1);
 await expect(page.locator('.unknown-peer')).toHaveCount(1);await expect(page.getByTestId('diagram')).toContainText('AP未確認');await expect(page.locator('.device-card[data-device="ap01"]')).toHaveCount(0);await expect(page.locator('.wifi-wave')).toHaveCount(1);
 await page.getByRole('button',{name:'全体表示',exact:true}).click();
 await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/connections-unknown-ap.png',fullPage:true});
 await page.getByLabel('表示する機器',{exact:true}).selectOption('wifi3');await expect(page.getByLabel('表示範囲')).toContainText('範囲外へつながるL1接続 1本');await expect(page.locator('.l1-connection')).toHaveCount(0);await page.getByText('範囲外へつながるL1接続 1本（図から省略）').click();await expect(page.getByLabel('表示範囲')).toContainText('ap01（ポート／無線IF未確認）');await expect(page.getByLabel('表示範囲')).toContainText('SSID: LayerMap-Office');await expect(page.getByLabel('表示範囲')).toContainText('Wi-Fi / ポート／無線IF未確認');
});

test('confirming an unknown wired port updates its actual anchor without stale placeholders',async({page,request})=>{
 const source=(await(await request.get('/api/samples/connection-status')).json()).yaml_text;
 const updated=source.replace('  ports:', '  ports:\n    - {id: sw01.p1, device: sw01, name: Gi1/0/1}').replace('"status":"port_unknown","endpoints":[{"port":"pc-a.eth0"},{"device":"sw01"}]','"status":"confirmed","endpoints":[{"port":"pc-a.eth0"},{"port":"sw01.p1"}]');
 await page.getByRole('textbox',{name:'YAMLエディター'}).fill(updated);await expect(page.getByLabel('検証結果')).toContainText('検証済み');
 const group=page.locator('.l1-connection[data-connection-id="wired-port-unknown"]');await expect(group).toHaveAttribute('data-connection-status','confirmed');await expect(group.locator('path')).not.toHaveAttribute('stroke-dasharray');await expect(page.locator('[data-layer="l1"] [data-element-id="sw01.p1"]')).toHaveCount(1);await expect(page.locator('.unresolved-endpoint[data-connection-id="wired-port-unknown"]')).toHaveCount(0);
});

test('Wi-Fi keeps layer tracing separate from radio association and help explains both dimensions',async({page})=>{
 await page.locator('[data-layer="l1"] [data-element-id="wifi1.wlan0"]').focus();await page.keyboard.press('Enter');await expect(page.getByLabel('層間対応の追跡')).toContainText('3行・2対応');await expect(page.locator('.trace-row[data-owner="ap01"]')).toHaveCount(0);
 await page.getByRole('button',{name:'ヘルプ',exact:true}).click();const help=page.getByRole('dialog');await help.getByRole('button',{name:'有線・Wi-Fi',exact:true}).click();await expect(help.getByRole('heading',{name:'有線・Wi-Fiと接続先の確認状況',exact:true})).toBeVisible();await expect(help).toContainText('peer_unknown');await expect(help).toContainText('SSIDからVLAN所属を自動で決めません');await page.keyboard.press('Escape');
 await page.setViewportSize({width:390,height:844});await page.getByLabel('表示する機器',{exact:true}).selectOption('wifi4');await expect(page.locator('.unknown-peer')).toHaveCount(1);await page.getByRole('tab',{name:'L1 物理'}).click();await expect(page.locator('[data-layer]')).toHaveCount(1);await page.getByRole('button',{name:'全体表示',exact:true}).click();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/connections-mobile.png',fullPage:true});
});
