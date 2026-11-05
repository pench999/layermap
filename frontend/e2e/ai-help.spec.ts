import {test,expect,type Page} from '@playwright/test';
async function yaml(page:Page){const p=page.waitForEvent('download');await page.getByRole('button',{name:'YAMLを保存',exact:true}).click();let result='';for await(const chunk of(await(await p).createReadStream())!)result+=chunk;return result;}
async function help(page:Page){await page.goto('/');await expect(page.getByLabel('検証結果')).toContainText('検証済み');await page.getByRole('button',{name:'ヘルプ',exact:true}).click();await page.getByRole('button',{name:'AIでYAMLを作成',exact:true}).click();}
test('help shows AI instructions and starter; downloaded UTF-8 Markdown matches the viewer and preserves YAML',async({page,request})=>{
 await page.goto('/');await expect(page.getByLabel('検証結果')).toContainText('検証済み');const before=await yaml(page);
 await page.getByRole('button',{name:'ヘルプ',exact:true}).click();await page.getByRole('button',{name:'AIでYAMLを作成',exact:true}).click();
 const files=[['instructions','AI向け指示書','LayerMap-YAML作成指示書.md'],['starter','使い方と開始プロンプト','使い方と開始プロンプト.md']];
 for(const [id,title,filename] of files){
  const document=(await(await request.get('/api/ai-docs/'+id)).json());
  await page.getByRole('button',{name:title+'を表示',exact:true}).click();const viewer=page.getByLabel(title+'の全文',{exact:true});await expect(viewer).toHaveText(document.content);
  const pending=page.waitForEvent('download');await page.getByRole('link',{name:title+'をダウンロード',exact:true}).click();const saved=await pending;expect(saved.suggestedFilename()).toBe(filename);let content='';for await(const chunk of(await saved.createReadStream())!)content+=chunk;expect(content).toBe(document.content);
  await page.getByRole('button',{name:title+'を閉じる',exact:true}).click();await expect(viewer).toHaveCount(0);
 }
 await page.getByRole('button',{name:'AI向け指示書を表示',exact:true}).click();await expect(page.getByLabel('AI向け指示書の全文',{exact:true})).toContainText('subnet_groups');
 await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/ai-help-documents.png',fullPage:true});
 await page.getByRole('button',{name:'ヘルプを閉じる',exact:true}).click();expect(await yaml(page)).toBe(before);
});
test('mobile document reading handles a failed fetch, retries and closes without horizontal overflow',async({page})=>{
 await page.setViewportSize({width:390,height:844});let attempts=0;await page.route('**/api/ai-docs/instructions',route=>++attempts===1?route.abort():route.continue());
 await help(page);await page.getByRole('button',{name:'AI向け指示書を表示',exact:true}).click();await expect(page.getByRole('alert')).toContainText('資料を読み込めませんでした');await expect(page.getByRole('link',{name:'AI向け指示書をダウンロード',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'資料の読み込みを再試行',exact:true}).click();await expect(page.getByLabel('AI向け指示書の全文',{exact:true})).toContainText('LayerMap YAML作成アシスタント');
 expect(await page.getByRole('dialog').evaluate(e=>e.scrollWidth<=e.clientWidth)).toBe(true);
 await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/ai-help-mobile.png',fullPage:true});
 await page.getByRole('button',{name:'ヘルプを閉じる',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
});
