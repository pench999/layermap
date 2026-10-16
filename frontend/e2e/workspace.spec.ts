import {test,expect} from '@playwright/test';

test.beforeEach(async({page})=>{
  await page.goto('/');
  await expect(page.getByLabel('検証結果')).toContainText('検証済み');
});

test('initial workspace and all layers',async({page})=>{
  await expect(page.getByRole('heading',{name:'ネットワーク ワークスペース'})).toBeVisible();
  for(const layer of ['l1','l2','l3']) await expect(page.locator('[data-layer="'+layer+'"]')).toHaveCount(1);
  await expect(page.getByLabel('検証結果')).toContainText('4 機器');
  await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/workspace-desktop.png',fullPage:true});
});

test('edit YAML updates diagram and error keeps last valid SVG',async({page,request})=>{
  const source=(await (await request.get('/api/sample')).json()).yaml_text;
  const editor=page.getByRole('textbox',{name:'YAMLエディター'});
  await editor.fill(source.replace('HQ-PC-01','EDITED-PC'));
  await expect(page.getByLabel('検証結果')).toContainText('検証済み');
  await expect(page.getByTestId('diagram')).toContainText('EDITED-PC');
  await editor.fill('devices: [');
  await expect(page.getByLabel('検証結果')).toContainText('入力を確認');
  await expect(page.getByTestId('diagram')).toContainText('EDITED-PC');
  await expect(page.getByText('現在のYAMLは未反映です。最後に正常生成した図を表示しています。')).toBeVisible();
  await expect(page.getByRole('button',{name:'SVGを書き出す'})).toBeDisabled();
  await editor.fill(source);
  await expect(page.getByLabel('検証結果')).toContainText('検証済み');
  await expect(page.getByRole('button',{name:'SVGを書き出す'})).toBeEnabled();
});

test('single layers, binding toggle and device highlight',async({page})=>{
  await page.getByRole('checkbox',{name:'層間対応'}).uncheck({force:true});
  await expect(page.locator('[data-binding]')).toHaveCount(0);
  await page.getByRole('checkbox',{name:'層間対応'}).check({force:true});
  await expect(page.locator('[data-binding]')).toHaveCount(2);
  for(const [label,layer] of [['L1 物理','l1'],['L2 VLAN','l2'],['L3 IP','l3']]){
    await page.getByRole('tab',{name:label}).click();
    await expect(page.locator('[data-layer]')).toHaveCount(1);
    await expect(page.locator('[data-layer="'+layer+'"]')).toHaveCount(1);
    await expect(page.locator('[data-binding]')).toHaveCount(0);
  }
  await page.getByRole('tab',{name:'全レイヤー'}).click();
  await expect(page.locator('[data-layer]')).toHaveCount(3);
  await page.getByLabel('機器の強調表示').selectOption('pc-a');
  await expect(page.locator('.selected-device')).toHaveCount(3);
  await expect(page.locator('.other-device').first()).toBeVisible();
  await page.getByLabel('機器の強調表示').selectOption('');
  await expect(page.locator('.selected-device')).toHaveCount(0);
});

test('file open and both downloads',async({page,request})=>{
  const sample=(await (await request.get('/api/sample')).json()).yaml_text;
  await page.locator('input[type=file]').setInputFiles({name:'office.yaml',mimeType:'application/yaml',buffer:Buffer.from(sample.replace('HQ-PC-01','IMPORTED-PC'))});
  await expect(page.getByTestId('diagram')).toContainText('IMPORTED-PC');
  await expect(page.getByLabel('検証結果')).toContainText('検証済み');
  const yamlDownload=page.waitForEvent('download');
  await page.getByRole('button',{name:'YAMLを保存'}).click();
  const yamlFile=await yamlDownload;
  expect(yamlFile.suggestedFilename()).toBe('office.yaml');
  const yamlStream=await yamlFile.createReadStream();let yamlText='';for await(const chunk of yamlStream!)yamlText+=chunk;
  expect(yamlText).toContain('IMPORTED-PC');
  const svgDownload=page.waitForEvent('download');
  await page.getByRole('button',{name:'SVGを書き出す'}).click();
  const svgFile=await svgDownload;
  expect(svgFile.suggestedFilename()).toBe('office-all.svg');
  const svgStream=await svgFile.createReadStream();let svg='';for await(const chunk of svgStream!)svg+=chunk;
  expect(svg).toContain('<svg');expect(svg).toContain('IMPORTED-PC');
});

test('late responses do not overwrite newer edits',async({page,request})=>{
  const source=(await (await request.get('/api/sample')).json()).yaml_text;
  await page.route('**/api/render',async route=>{
    const data=route.request().postDataJSON();
    if(data.yaml_text.includes('OLDER-PC'))await new Promise(resolve=>setTimeout(resolve,1600));
    try{await route.continue();}catch{}
  });
  const editor=page.getByRole('textbox',{name:'YAMLエディター'});
  const oldRequest=page.waitForRequest(r=>r.url().endsWith('/api/render')&&r.postData()!.includes('OLDER-PC'));
  await editor.fill(source.replace('HQ-PC-01','OLDER-PC'));await oldRequest;
  await editor.fill(source.replace('HQ-PC-01','NEWER-PC'));
  await expect(page.getByTestId('diagram')).toContainText('NEWER-PC');
  await page.waitForTimeout(2000);
  await expect(page.getByTestId('diagram')).not.toContainText('OLDER-PC');
});

test('mobile layout, zoom and fit controls',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await expect(page.getByRole('button',{name:'YAMLを開く'})).toBeVisible();
  await page.getByRole('tab',{name:'L1 物理'}).click();
  await expect(page.locator('[data-layer]')).toHaveCount(1);
  await expect(page.locator('[data-layer="l1"]')).toHaveCount(1);
  await expect(page.getByLabel('検証結果')).toContainText('検証済み');
  await page.getByRole('button',{name:'拡大',exact:true}).click();
  await page.getByRole('button',{name:'縮小',exact:true}).click();
  await page.getByRole('button',{name:'全体表示'}).click();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
  await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/workspace-mobile.png',fullPage:true});
});


test('help opens without replacing edits and supports navigation and Escape',async({page})=>{
  await page.getByRole('button',{name:'ヘルプ',exact:true}).click();
  const help=page.getByRole('dialog',{name:'YAMLの書き方と構成の追加'});
  await expect(help).toBeVisible();
  await expect(help).toContainText('bindings.l2_to_l1');
  await expect(help).toContainText('serial_number');
  await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/help-desktop.png',fullPage:true});
  await help.getByRole('button',{name:'VLANを追加',exact:true}).click();
  await expect(help.getByRole('heading',{name:'新しいVLAN 30を追加する'})).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(help).toHaveCount(0);
  await expect(page.getByRole('button',{name:'ヘルプ',exact:true})).toBeFocused();
  await expect(page.getByLabel('検証結果')).toContainText('4 機器');
});

test('three samples load from selector including repeat loading and download name',async({page})=>{
  await page.getByLabel('サンプル構成').selectOption('base');
  const redraw=page.waitForResponse(r=>r.url().endsWith('/api/render')&&r.status()===200);
  await page.getByRole('button',{name:'サンプルを読み込む',exact:true}).click();
  await redraw;
  await expect(page.locator('.toast')).toContainText('サンプルを読み込みました');
  await expect(page.getByLabel('検証結果')).toContainText('検証済み');
  for(const [id,vlans] of [['add-pc','2 VLAN'],['add-vlan','3 VLAN']]){
    await page.getByLabel('サンプル構成').selectOption(id);
    await page.getByRole('button',{name:'サンプルを読み込む',exact:true}).click();
    await expect(page.getByLabel('検証結果')).toContainText('5 機器');
    await expect(page.getByLabel('検証結果')).toContainText(vlans);
    await expect(page.getByLabel('検証結果')).toContainText('検証済み');
    await expect(page.getByTestId('diagram')).toContainText('HQ-PC-03');
  }
  await expect(page.getByTestId('diagram')).toContainText('192.168.30.30/24');
  const download=page.waitForEvent('download');
  await page.getByRole('button',{name:'YAMLを保存'}).click();
  expect((await download).suggestedFilename()).toBe('02-add-vlan30.yaml');
});

test('help sample loading respects cancel and acceptance of unsaved changes',async({page})=>{
  await page.getByRole('textbox',{name:'YAMLエディター'}).fill('name: MY-UNSAVED-DRAFT');
  await page.getByRole('button',{name:'ヘルプ',exact:true}).click();
  const help=page.getByRole('dialog');
  page.once('dialog',dialog=>dialog.dismiss());
  await help.getByRole('button',{name:'機器追加版を読み込む',exact:true}).click();
  await expect(help).toBeVisible();
  page.once('dialog',dialog=>dialog.accept());
  await help.getByRole('button',{name:'機器追加版を読み込む',exact:true}).click();
  await expect(help).toHaveCount(0);
  await expect(page.getByLabel('検証結果')).toContainText('5 機器');
  await expect(page.getByTestId('diagram')).toContainText('HQ-PC-03');
});

test('sample network failure keeps the editable document',async({page})=>{
  await page.route('**/api/samples/add-vlan',route=>route.fulfill({status:500,body:'failed'}));
  const before=await page.getByTestId('diagram').innerHTML();
  await page.getByLabel('サンプル構成').selectOption('add-vlan');
  await page.getByRole('button',{name:'サンプルを読み込む',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('編集内容は保持されています');
  await expect(page.getByLabel('検証結果')).toContainText('検証済み');
  expect(await page.getByTestId('diagram').innerHTML()).toBe(before);
});

test('editing during sample download requires another confirmation',async({page})=>{
  await page.route('**/api/samples/add-pc',async route=>{
    const response=await route.fetch();
    await new Promise(resolve=>setTimeout(resolve,900));
    await route.fulfill({response});
  });
  await page.getByLabel('サンプル構成').selectOption('add-pc');
  const request=page.waitForRequest(r=>r.url().endsWith('/api/samples/add-pc'));
  await page.getByRole('button',{name:'サンプルを読み込む',exact:true}).click();await request;
  page.once('dialog',dialog=>dialog.dismiss());
  await page.getByRole('textbox',{name:'YAMLエディター'}).fill('name: KEEP-LATEST-EDIT');
  await expect(page.getByRole('button',{name:'サンプルを読み込む',exact:true})).toBeEnabled();
  await expect(page.getByRole('textbox',{name:'YAMLエディター'})).toContainText('KEEP-LATEST-EDIT');
  await expect(page.getByLabel('検証結果')).toContainText('入力を確認');
});

test('help fits a mobile viewport',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('button',{name:'ヘルプ',exact:true}).click();
  const help=page.getByRole('dialog');
  await expect(help).toBeVisible();
  expect(await help.evaluate(el=>el.scrollWidth<=window.innerWidth)).toBeTruthy();
  await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/help-mobile.png',fullPage:false});
  await page.getByRole('button',{name:'ヘルプを閉じる'}).click();
  await expect(help).toHaveCount(0);
});


test('equipment frames contain distinct interfaces and support port clicks',async({page})=>{
  for(const layer of ['l1','l2','l3']){
    const group=page.locator('[data-layer="'+layer+'"]');
    await expect(group.locator('g.device-card')).toHaveCount(4);
    await expect(group.locator('g.device-card[data-device="sw01"]')).toHaveCount(1);
    await expect(group.locator('g.device-card[data-device="sw01"] > rect.device-frame')).toHaveCount(1);
  }
  const switchL1=page.locator('[data-layer="l1"] g.device-card[data-device="sw01"]');
  await expect(switchL1.locator('[data-element-id]')).toHaveCount(3);
  await expect(switchL1).toContainText('DEMO-SW-0001');
  await expect(page.locator('[data-layer="l3"] g.device-card[data-device="sw01"]')).toContainText('L3インターフェースなし');
  await page.getByRole('tab',{name:'L1 物理'}).click();
  await expect(page.locator('[data-layer]')).toHaveCount(1);
  await expect(page.getByLabel('検証結果')).toContainText('検証済み');
  await page.locator('[data-element-id="sw01.p2"]').click();
  await expect(page.getByLabel('機器の強調表示')).toHaveValue('sw01');
  await expect(page.locator('.selected-device')).toHaveCount(1);
  await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/grouped-l1.png',fullPage:true});
  await page.getByRole('tab',{name:'L2 VLAN'}).click();
  await expect(page.locator('[data-layer="l2"]')).toHaveCount(1);
  await expect(page.getByLabel('検証結果')).toContainText('検証済み');
  await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/grouped-l2.png',fullPage:true});
  await page.getByRole('tab',{name:'L3 IP'}).click();
  await expect(page.locator('[data-layer="l3"]')).toHaveCount(1);
  await expect(page.getByLabel('検証結果')).toContainText('検証済み');
  await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/grouped-l3.png',fullPage:true});
});
