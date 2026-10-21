import {test,expect} from '@playwright/test';
test('L2 switch groups access ports by VLAN and preserves exact port tracing and source selection',async({page})=>{
 await page.goto('/');await expect(page.getByLabel('検証結果')).toContainText('検証済み');
 await page.getByLabel('サンプル構成',{exact:true}).selectOption('three-48port');await page.getByRole('button',{name:'サンプルを読み込む',exact:true}).click();await expect(page.locator('.diagram .interface-row')).toHaveCount(414);
 await page.getByLabel('表示する機器',{exact:true}).selectOption('sw01');await expect(page.locator('.diagram .interface-row')).toHaveCount(98);
 const oldHeight=Number(await page.locator('.diagram [data-device-layer="l2"] .device-frame').getAttribute('height'));
 await page.getByRole('tab',{name:'L2 VLAN',exact:true}).click();await expect(page.locator('.diagram [data-layer]')).toHaveCount(1);await expect(page.getByLabel('検証結果')).toContainText('検証済み');
 await expect(page.locator('.diagram .compact-port')).toHaveCount(47);
 const height=Number(await page.locator('.diagram .device-frame').getAttribute('height'));expect(height).toBeLessThan(oldHeight/3);
 const ids=await page.locator('.diagram .switch-vlan-group').evaluateAll(groups=>groups.map(e=>e.getAttribute('data-network-id')));expect(new Set(ids).size).toBe(ids.length);expect(ids.length).toBeGreaterThan(0);
 const group=page.locator('.diagram .switch-vlan-group').first();const id=await group.getAttribute('data-network-id');await group.focus();await page.keyboard.press('Enter');await expect(page.getByLabel('図面とYAMLの対応',{exact:true})).toContainText('l2.vlans / '+id);await expect(group).toHaveAttribute('aria-pressed','true');
 await page.keyboard.press('Escape');await expect(group).toHaveAttribute('aria-pressed','false');
 await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/compact-switch-vlans.png',fullPage:true});
 const port=page.locator('.diagram .compact-port[data-element-id="sw01.p48.l2"]');await expect(port).toContainText('Gi1/0/48');await port.focus();await page.keyboard.press('Enter');
 await expect(page.locator('.diagram [data-layer]')).toHaveCount(3);await expect(page.getByLabel('層間対応の追跡')).toContainText('sw01.p48');await expect(page.getByLabel('図面とYAMLの対応',{exact:true})).toContainText('l2.interfaces / sw01.p48.l2');
});
