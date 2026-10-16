import {test,expect,type Page} from '@playwright/test';
async function source(page:Page){const waiting=page.waitForEvent('download');await page.getByRole('button',{name:'YAMLを保存',exact:true}).click();const d=await waiting;let s='';for await(const c of (await d.createReadStream())!)s+=c;return s;}
async function upload(page:Page,s:string){page.once('dialog',d=>d.accept());await page.locator('input[type=file]').setInputFiles({name:'manual.yaml',mimeType:'application/yaml',buffer:Buffer.from(s)});await expect(page.getByLabel('検証結果')).toContainText('検証済み');}
async function device(page:Page,id='test-pc',wifi=false,ip=false){
 await page.getByRole('button',{name:'機器を追加',exact:true}).click();const d=page.getByRole('dialog',{name:'機器追加ウィザード'});
 await d.getByLabel('機器ID', {exact:false}).fill(id);await d.getByLabel('機器名',{exact:true}).fill('追加PC😀');await d.getByLabel('シリアルNo').fill('SN-0001');await d.getByLabel('拠点',{exact:true}).fill('本社');
 await d.getByRole('button',{name:'次へ',exact:true}).click();if(wifi)await d.getByLabel('ポートの方式').selectOption('wifi');await d.getByRole('button',{name:'次へ',exact:true}).click();
 await d.getByLabel('VLAN 10 · vlan-office').check();if(ip){await d.getByLabel('IPアドレス / プレフィックス').fill('192.168.10.50/24');await d.getByLabel('所属サブネット').selectOption('net-office');await d.getByLabel('IPに対応するVLAN').selectOption('vlan-office');await d.getByLabel('デフォルトゲートウェイ').fill('192.168.10.1');}
 await d.getByRole('button',{name:'変更内容を確認',exact:true}).click();await expect(d.getByRole('heading',{name:'変更内容の確認'})).toBeVisible();return d;
}
async function applyDevice(page:Page,id='test-pc',wifi=false,ip=false){const d=await device(page,id,wifi,ip);await d.getByRole('button',{name:'YAMLに適用'}).click();await expect(d).toHaveCount(0);await expect(page.getByLabel('検証結果')).toContainText('検証済み');}
async function comment(page:Page,value:string){const ed=page.getByRole('textbox',{name:'YAMLエディター'});await ed.focus();await page.keyboard.press('Control+Home');await page.keyboard.insertText(value);await expect(page.getByLabel('検証結果')).toContainText('検証済み');}
async function at(page:Page,text:string,index:number){await page.getByRole('textbox',{name:'YAMLエディター'}).focus();await page.keyboard.press('Control+Home');const prefix=text.slice(0,index).replace(/\r\n|\r/g,'\n').split('\n');for(let n=1;n<prefix.length;n++)await page.keyboard.press('ArrowDown');await page.keyboard.press('Home');await page.keyboard.press('Home');for(let n=0;n<prefix[prefix.length-1].length;n++)await page.keyboard.press('ArrowRight');}
test.beforeEach(async({page})=>{await page.goto('/');await expect(page.getByLabel('検証結果')).toContainText('検証済み');});

test('wizard preserves comments, CRLF and Unicode; undo retains later manual edits',async({page})=>{
 const base='# 😀 手動コメント\r\n'+(await source(page)).replace(/\n/g,'\r\n').replace('schema: lan-example/v1','schema: "lan-example/v1" # 引用符保持');await upload(page,base);
 const d=await device(page,'test-pc',false,true);await expect(d.locator('.input-diff')).toContainText('SN-0001');await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/input-device-review.png',fullPage:true});
 await d.getByRole('button',{name:'YAMLに適用'}).click();await expect(page.getByLabel('検証結果')).toContainText('5 機器');await expect(page.locator('[data-layer="l3"] [data-element-id="test-pc.ip"]')).toHaveCount(1);
 const applied=await source(page);expect(applied).toContain('# 引用符保持');expect(applied.replace(/\r\n/g,'')).not.toContain('\n');
 await comment(page,'# あとから手動で追記\n');await page.getByRole('button',{name:'直前のフォーム操作を取り消す'}).click();await expect(page.getByLabel('検証結果')).toContainText('4 機器');expect(await source(page)).toBe('# あとから手動で追記\r\n'+base);
});

test('review cancel and back keep source untouched and duplicate IDs are rejected',async({page})=>{
 const base=await source(page);const d=await device(page);await d.getByRole('button',{name:'入力へ戻る'}).click();await d.getByRole('button',{name:'戻る',exact:true}).click();await d.getByRole('button',{name:'戻る',exact:true}).click();await d.getByLabel('機器ID').fill('pc-a');await d.getByRole('button',{name:'次へ',exact:true}).click();await d.getByRole('button',{name:'次へ',exact:true}).click();await d.getByRole('button',{name:'変更内容を確認',exact:true}).click();await expect(d.getByRole('alert')).toContainText('既に使われています');await d.getByRole('button',{name:'キャンセル',exact:true}).click();expect(await source(page)).toBe(base);
});

test('Wi-Fi unknown AP and wired unknown port are selectable and rendered',async({page})=>{
 await applyDevice(page,'wifi-new',true);await page.getByRole('button',{name:'接続を追加',exact:true}).click();let d=page.getByRole('dialog',{name:'接続フォーム'});await d.getByLabel('接続ID').fill('wifi-new-link');await d.getByLabel('接続方式',{exact:true}).selectOption('wifi');await d.getByLabel('接続先の確定状況').selectOption('peer_unknown');await d.getByLabel('接続元ポート').selectOption('wifi-new.wlan0');await d.getByLabel('SSID').fill('Office');await d.getByRole('button',{name:'変更内容を確認'}).click();await d.getByRole('button',{name:'YAMLに適用'}).click();await expect(page.locator('.l1-connection[data-connection-id="wifi-new-link"]')).toHaveAttribute('data-connection-status','peer_unknown');
 await applyDevice(page,'wired-new');await page.getByRole('button',{name:'接続を追加',exact:true}).click();d=page.getByRole('dialog',{name:'接続フォーム'});await d.getByLabel('接続ID').fill('wired-new-link');await d.getByLabel('接続先の確定状況').selectOption('port_unknown');await d.getByLabel('接続元ポート').selectOption('wired-new.eth0');await d.getByLabel('接続先機器',{exact:true}).selectOption('sw01');await expect(d.getByLabel('接続元ポート').locator('option[value="pc-a.eth0"]')).toHaveAttribute('disabled','');await d.getByRole('button',{name:'変更内容を確認'}).click();await d.getByRole('button',{name:'YAMLに適用'}).click();await expect(page.locator('.l1-connection[data-connection-id="wired-new-link"]')).toHaveAttribute('data-connection-status','port_unknown');
 await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/input-connections.png',fullPage:true});await page.getByRole('button',{name:'直前のフォーム操作を取り消す'}).click();await expect(page.getByLabel('検証結果')).toContainText('4 L1接続');await expect(page.locator('.l1-connection[data-connection-id="wired-new-link"]')).toHaveCount(0);
});

test('editing an added record blocks form undo without deleting manual changes',async({page})=>{
 await applyDevice(page);const current=await source(page);await at(page,current,current.indexOf('追加PC'));for(let n=0;n<4;n++)await page.keyboard.press('Shift+ArrowRight');await page.keyboard.insertText('編集済PC');await expect(page.getByLabel('検証結果')).toContainText('検証済み');await expect(page.getByRole('button',{name:'直前のフォーム操作を取り消す'})).toBeDisabled();await expect(page.getByLabel('入力サポート',{exact:true})).toContainText('追加部分が手動編集');expect(await source(page)).toContain('編集済PC');
});

test('undo refuses to break manually added references',async({page})=>{
 await applyDevice(page);await comment(page,'# untouched manual note\n');const before=await source(page);const extra='    - {id: manual-link, kind: wired, status: peer_unknown, endpoints: [{port: test-pc.eth0}, {unknown: true}]}\n';
 // Insert a new, independent list before l2 rather than replacing the document.
 await at(page,before,before.indexOf('\nl2:\n')+1);await page.keyboard.insertText('  connections:\n'+extra+'\n');await expect(page.getByLabel('検証結果')).toContainText('4 L1接続');
 await page.getByRole('button',{name:'直前のフォーム操作を取り消す'}).click();await expect(page.getByRole('status').filter({hasText:'取り消せません'})).toBeVisible();const after=await source(page);expect(after).toContain('manual-link');expect(after).toContain('test-pc');expect(after).toContain('# untouched manual note');expect(after.length).toBeGreaterThan(before.length);
});

test('native undo treats a form apply as one operation',async({page})=>{
 const before=await source(page);await applyDevice(page,'history-pc',false,true);await page.getByRole('textbox',{name:'YAMLエディター'}).focus();await page.keyboard.press('Control+z');await expect(page.getByLabel('検証結果')).toContainText('4 機器');expect(await source(page)).toBe(before);
});

test('mobile wizard and confirmed port connection are usable',async({page})=>{
 await page.setViewportSize({width:390,height:844});await applyDevice(page,'new-a');await applyDevice(page,'new-b');await page.getByRole('button',{name:'接続を追加',exact:true}).click();const d=page.getByRole('dialog',{name:'接続フォーム'});await d.getByLabel('接続ID').fill('confirmed-new');await d.getByLabel('接続元ポート').selectOption('new-a.eth0');await d.getByLabel('接続先ポート',{exact:true}).selectOption('new-b.eth0');await d.getByRole('button',{name:'変更内容を確認'}).click();await page.screenshot({path:(process.env.QA_ARTIFACTS||'test-results')+'/input-mobile-review.png',fullPage:true});await d.getByRole('button',{name:'YAMLに適用'}).click();await expect(page.locator('.l1-connection[data-connection-id="confirmed-new"]')).toHaveAttribute('data-connection-status','confirmed');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});


test('large validated inventories can use wizard without discarding scope or hidden devices',async({page})=>{
 await page.getByLabel('サンプル構成').selectOption('multi-site');await page.getByRole('button',{name:'サンプルを読み込む',exact:true}).click();await expect(page.getByLabel('検証結果')).toContainText('36 機器');
 await page.getByRole('button',{name:'機器を追加',exact:true}).click();const d=page.getByRole('dialog',{name:'機器追加ウィザード'});await d.getByLabel('機器ID').fill('large-new');await d.getByRole('button',{name:'次へ',exact:true}).click();await d.getByRole('button',{name:'次へ',exact:true}).click();await d.getByLabel('L2と層間対応を追加する').uncheck();await d.getByRole('button',{name:'変更内容を確認'}).click();await d.getByRole('button',{name:'YAMLに適用'}).click();await expect(page.getByLabel('検証結果')).toContainText('37 機器');await expect(page.getByLabel('表示範囲の案内')).toBeVisible();await page.getByRole('button',{name:'直前のフォーム操作を取り消す'}).click();await expect(page.getByLabel('検証結果')).toContainText('36 機器');
});

test('form edits invalidate an in-flight preview and stale result cannot be applied',async({page})=>{
 let release!:()=>void;const gate=new Promise<void>(r=>release=r);let entered!:()=>void;const arrived=new Promise<void>(r=>entered=r);
 await page.route('**/api/assist/preview',async route=>{const response=await route.fetch();entered();await gate;await route.fulfill({response}).catch(()=>{});});
 await page.getByRole('button',{name:'接続を追加',exact:true}).click();const d=page.getByRole('dialog',{name:'接続フォーム'});await d.getByLabel('接続ID').fill('unused');await d.getByLabel('接続先の確定状況').selectOption('peer_unknown');
 // Existing wired ports are all occupied, so add a Wi-Fi device first instead.
 await d.getByRole('button',{name:'キャンセル',exact:true}).click();await page.unroute('**/api/assist/preview');await applyDevice(page,'race-wifi',true);
 await page.route('**/api/assist/preview',async route=>{const response=await route.fetch();entered();await gate;await route.fulfill({response}).catch(()=>{});});
 await page.getByRole('button',{name:'接続を追加',exact:true}).click();await d.getByLabel('接続ID').fill('race-first');await d.getByLabel('接続方式',{exact:true}).selectOption('wifi');await d.getByLabel('接続先の確定状況').selectOption('peer_unknown');await d.getByLabel('接続元ポート').selectOption('race-wifi.wlan0');await d.getByRole('button',{name:'変更内容を確認'}).click();await arrived;await d.getByLabel('備考').fill('最新の入力');release();await page.unroute('**/api/assist/preview');await expect(d.getByRole('button',{name:'YAMLに適用'})).toHaveCount(0);await d.getByRole('button',{name:'変更内容を確認'}).click();await expect(d.locator('.input-diff')).toContainText('最新の入力');await d.getByRole('button',{name:'YAMLに適用'}).click();await expect(page.locator('.l1-connection[data-connection-id="race-first"]')).toHaveCount(1);expect(await source(page)).toContain('最新の入力');
});
