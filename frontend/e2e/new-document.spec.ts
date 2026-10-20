import {test,expect,type Page} from '@playwright/test';
const editor=(page:Page)=>page.getByRole('textbox',{name:'YAMLエディター'});
async function save(page:Page){const wait=page.waitForEvent('download');await page.getByRole('button',{name:'YAMLを保存',exact:true}).click();const file=await wait;let text='';for await(const chunk of (await file.createReadStream())!)text+=chunk;return {text,name:file.suggestedFilename()};}
async function empty(page:Page){await expect(page.getByLabel('検証結果')).toContainText('0 機器');await expect(page.getByRole('heading',{name:'機器を追加して始めましょう'})).toBeVisible();await expect(page.getByTestId('diagram')).toHaveCount(0);await expect(page.getByRole('button',{name:'複数YAMLを統合',exact:true})).toHaveCount(1);await expect(page.getByRole('button',{name:'VPN接続定義を読み込む',exact:true})).toHaveCount(1);await expect(page.getByRole('button',{name:'機器を追加',exact:true})).toHaveCount(1);await expect(page.getByRole('button',{name:'SVGを書き出す'})).toBeDisabled();}
test.beforeEach(async({page})=>{await page.goto('/');await expect(page.getByLabel('検証結果')).toContainText('検証済み');});

test('new document confirms unsaved edits and cancel preserves editor, selection and filters',async({page,request})=>{
 const source=(await (await request.get('/api/sample')).json()).yaml_text.replace('HQ-PC-01','KEEP-EDIT');await editor(page).fill(source);await expect(page.getByTestId('diagram')).toContainText('KEEP-EDIT');
 await page.getByLabel('表示する機器',{exact:true}).selectOption('pc-a');await expect(page.locator('.diagram .device-card')).toHaveCount(3);
 const row=page.locator('.diagram [data-layer="l1"] .interface-row').first();await row.focus();await page.keyboard.press('Enter');await expect(page.locator('.cm-yaml-definition')).not.toHaveCount(0);
 page.once('dialog',async dialog=>{expect(dialog.message()).toContain('未保存');await dialog.dismiss();});await page.getByRole('button',{name:'新規作成',exact:true}).click();
 await expect(editor(page)).toContainText('KEEP-EDIT');await expect(page.getByLabel('表示する機器',{exact:true})).toHaveValue('pc-a');await expect(page.locator('.cm-yaml-definition')).not.toHaveCount(0);await expect(page.getByTestId('diagram')).toContainText('KEEP-EDIT');
 page.once('dialog',dialog=>dialog.accept());await page.getByRole('button',{name:'新規作成',exact:true}).click();await empty(page);await expect(page.locator('.cm-yaml-definition,.cm-yaml-reference')).toHaveCount(0);await expect(page.getByLabel('表示する機器',{exact:true})).toHaveValue('');await expect(page.getByLabel('層間対応の追跡')).toHaveCount(0);
});

test('new document clears invalid preview, layer state, scopes and undo history and saves valid YAML',async({page,request})=>{
 await page.getByRole('checkbox',{name:'層間対応'}).uncheck({force:true});await page.getByRole('tab',{name:'L3 IP',exact:true}).click();await page.getByLabel('表示する拠点',{exact:true}).selectOption({index:1});await page.getByRole('button',{name:'拡大',exact:true}).click();await editor(page).fill('broken: [');await expect(page.getByLabel('検証結果')).toContainText('入力を確認');
 page.once('dialog',dialog=>dialog.accept());await page.getByRole('button',{name:'新規作成',exact:true}).click();await empty(page);
 await expect(page.getByRole('tab',{name:'全レイヤー',exact:true})).toHaveAttribute('aria-selected','true');await expect(page.getByRole('checkbox',{name:'層間対応'})).toBeChecked();for(const label of ['表示する拠点','表示する機器群'])await expect(page.getByLabel(label,{exact:true})).toHaveValue('null');await expect(page.getByLabel('表示する対応関係',{exact:true})).toHaveValue('');await expect(page.locator('.zoom-controls')).toContainText('60%');await expect(page.locator('.saved')).toContainText('未保存');
 await editor(page).focus();await page.keyboard.press('Control+z');await expect(editor(page)).not.toContainText('broken');await empty(page);
 const saved=await save(page);expect(saved.name).toBe('untitled.yaml');expect(saved.text).toContain('devices: []');expect(saved.text).not.toContain('pc-a');const rendered=await request.post('/api/render',{data:{yaml_text:saved.text}});expect(rendered.ok()).toBeTruthy();expect((await rendered.json()).counts.devices).toBe(0);
 // A saved document can be replaced without a confirmation dialog.
 page.on('dialog',dialog=>{throw Error('Unexpected confirmation: '+dialog.message());});await page.getByRole('button',{name:'新規作成',exact:true}).click();await empty(page);
 await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/new-document-desktop.png',fullPage:true});
});

test('late render and sample responses cannot replace a newly created document',async({page,request})=>{
 let release!:()=>void,arrived!:()=>void,completed!:()=>void;const gate=new Promise<void>(r=>release=r),arrival=new Promise<void>(r=>arrived=r),completion=new Promise<void>(r=>completed=r);await page.route('**/api/samples/add-pc',async route=>{const response=await route.fetch();arrived();await gate;await route.fulfill({response}).catch(()=>{});completed();});
 await page.getByLabel('サンプル構成',{exact:true}).selectOption('add-pc');await page.getByRole('button',{name:'サンプルを読み込む',exact:true}).click();await arrival;await page.getByRole('button',{name:'新規作成',exact:true}).click();await empty(page);release();await completion;await expect(page.getByLabel('サンプル構成',{exact:true})).toHaveValue('base');
 const source=(await (await request.get('/api/sample')).json()).yaml_text.replace('HQ-PC-01','LATE-OLD');let releaseRender!:()=>void,renderArrived!:()=>void,renderCompleted!:()=>void;const renderGate=new Promise<void>(r=>releaseRender=r),renderArrival=new Promise<void>(r=>renderArrived=r),renderCompletion=new Promise<void>(r=>renderCompleted=r);await page.route('**/api/render',async route=>{if(!route.request().postData()!.includes('LATE-OLD')){await route.continue();return;}const response=await route.fetch();renderArrived();await renderGate;await route.fulfill({response}).catch(()=>{});renderCompleted();});
 await editor(page).fill(source);await renderArrival;page.once('dialog',dialog=>dialog.accept());await page.getByRole('button',{name:'新規作成',exact:true}).click();await empty(page);releaseRender();await renderCompletion;await expect(editor(page)).not.toContainText('LATE-OLD');await empty(page);
});

test('mobile new document starts the first device wizard and can undo back to zero devices',async({page})=>{
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'新規作成',exact:true}).click();await empty(page);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/new-document-mobile.png',fullPage:true});
 await page.getByRole('button',{name:'機器を追加',exact:true}).click();const dialog=page.getByRole('dialog',{name:'機器追加ウィザード'});await dialog.getByLabel('機器ID（必須・変更しない識別子）',{exact:true}).fill('first-pc');await dialog.getByLabel('機器名',{exact:true}).fill('最初のPC');await dialog.getByRole('button',{name:'次へ',exact:true}).click();await dialog.getByRole('button',{name:'次へ',exact:true}).click();await expect(dialog.getByRole('checkbox',{name:'L2と層間対応を追加する'})).not.toBeChecked();await dialog.getByRole('button',{name:'変更内容を確認',exact:true}).click();await expect(dialog.getByLabel('変更内容の確認')).toBeVisible();await dialog.getByRole('button',{name:'YAMLに適用',exact:true}).click();await expect(page.getByLabel('検証結果')).toContainText('1 機器');await expect(page.getByTestId('diagram')).toContainText('最初のPC');await page.getByRole('button',{name:'直前のフォーム操作を取り消す',exact:true}).click();await empty(page);
});

test('new document while the initial sample is loading ignores the late sample',async({page})=>{
 let release!:()=>void,arrived!:()=>void,completed!:()=>void;const gate=new Promise<void>(r=>release=r),arrival=new Promise<void>(r=>arrived=r),completion=new Promise<void>(r=>completed=r);
 await page.route('**/api/sample',async route=>{const response=await route.fetch();arrived();await gate;await route.fulfill({response}).catch(()=>{});completed();});
 await page.reload({waitUntil:'domcontentloaded'});await arrival;await page.getByRole('button',{name:'新規作成',exact:true}).click();await empty(page);release();await completion;await empty(page);await expect(editor(page)).toContainText('devices: []');
});
