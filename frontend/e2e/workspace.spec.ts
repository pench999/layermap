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
  await expect(page.locator('.selected-device')).toHaveCount(4);
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
