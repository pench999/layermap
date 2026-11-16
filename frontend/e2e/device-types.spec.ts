import {test,expect} from '@playwright/test';

test('four device types have distinct icons and consistent Japanese labels in every layer',async({page})=>{
 await page.goto('/');
 await expect(page.getByLabel('検証結果')).toContainText('検証済み');
 await expect(page.locator('[data-device="gw01"] [data-device-type="internet-gateway"]')).toHaveCount(3);
 await page.getByLabel('サンプル構成',{exact:true}).selectOption('device-types');
 await page.getByRole('button',{name:'サンプルを読み込む',exact:true}).click();
 await expect(page.locator('.device-type[data-device-type="router"]')).toHaveCount(3);
 const types=[['host','ホスト'],['l2-switch','L2スイッチ'],['l3-switch','L3スイッチ'],['router','ルーター']];
 for (const layer of ['l1','l2','l3']) {
  const panel=page.locator('[data-layer="'+layer+'"]');
  const paths=new Set<string|null>();
  for(const [kind,label] of types){
   const badge=panel.locator('[data-device-type="'+kind+'"]');
   await expect(badge.locator('.device-type-label')).toHaveText(label);
   paths.add(await badge.locator('.device-type-icon').getAttribute('d'));
  }
  expect(paths.size).toBe(4);
 }
 await page.getByRole('tab',{name:'L3 IP',exact:true}).click();
 await expect(page.locator('.diagram [data-layer]')).toHaveCount(1);
 await page.getByRole('button',{name:'全体表示',exact:true}).click();
 const labels=page.locator('[data-layer="l3"] .device-type-label');
 const preview=await labels.evaluateAll(nodes=>nodes.map(node=>({width:node.getBoundingClientRect().width,height:node.getBoundingClientRect().height})));
 expect(preview).toHaveLength(4);
 expect(Math.min(...preview.map(label=>label.height))).toBeGreaterThan(7);
 await page.locator('svg').screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/device-types-fit.png'});
});
