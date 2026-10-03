import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const page=await browser.newPage({viewport:{width:1304,height:884},reducedMotion:'reduce'});
const source={id:'relation-source',kind:'agent',name:'Mock relation source',path:'C:/mock/source',source:'测试',status:'已发现',description:'Synthetic fixture only',vendor:'Fixture'};
const target={id:'relation-target',kind:'directory',name:'Mock target folder',path:'C:/mock/target',source:'测试',status:'已发现'};
const automatic={from:source.id,to:target.id,label:'扫描使用'};
let manual=[{id:'missing-edge',from:source.id,to:'missing-fixture',label:'历史对象关联',manual:true,missing:true}],listFails=false,offline=false;
const writes=[],errors=[];
page.on('pageerror',error=>errors.push(error.message));
await page.route('**/api/**',async route=>{
 const request=route.request(),path=new URL(request.url()).pathname;
 if(request.method()!=='POST'){
  if(path==='/api/state'){
   if(offline)return route.abort();
   return route.fulfill({json:{token:'mock-token',scan:{running:false},data:{objects:[source,target],relations:[automatic,...manual.filter(item=>!item.missing)],notes:{},changes:[],issues:[],disks:[],at:'2026-10-03T00:00:00Z',scope:'synthetic fixture',machine:'Mock'}}});
  }
  return route.fulfill({json:{cpu:0,memory:0}});
 }
 const body=request.postDataJSON();writes.push({path,body});
 if(path==='/api/relation/list')return route.fulfill(listFails?{status:500,json:{error:'模拟读取失败，请重试。'}}:{json:{relations:manual}});
 if(path==='/api/relation/add'){
  assert.equal(body.from_id,source.id);assert.equal(body.to_id,target.id);assert.equal(body.label,'项目使用');
  await new Promise(resolve=>setTimeout(resolve,300));
  const relation={id:'added-edge',from:body.from_id,to:body.to_id,label:body.label,manual:true,missing:false};manual.push(relation);
  return route.fulfill({json:{relation}});
 }
 if(path==='/api/relation/remove'){manual=manual.filter(item=>item.id!==body.id);return route.fulfill({json:{ok:true}})}
 if(path==='/api/assistant/list')return route.fulfill({json:{sessions:[]}});
 if(path==='/api/action/list'||path==='/api/mcp-action/list')return route.fulfill({json:{actions:[]}});
 return route.fulfill({status:400,json:{error:'Unexpected mocked operation'}});
});
try{
 await page.goto('http://127.0.0.1:8765');
 await page.locator('.agent-row').filter({hasText:source.name}).click();
 await page.locator('.object-preview').click();
 await page.getByRole('button',{name:/^关联 \d/}).click();
 const editor=page.locator('.relation-editor');
 await expect(editor.getByText('未收录对象 · missing-fixture',{exact:true})).toBeVisible();
 await editor.getByLabel('关联到哪个对象',{exact:true}).fill('Mock target');
 await editor.getByRole('button',{name:'选择 '+target.name,exact:true}).click();
 await editor.getByLabel('关联说明',{exact:true}).fill('项目使用');
 await editor.getByRole('button',{name:'保存人工关联',exact:true}).click();
 await expect(page.getByRole('button',{name:'关闭详情',exact:true})).toBeDisabled();
 await expect(editor.getByRole('status').filter({hasText:'人工关联已保存。'})).toBeVisible();
 await expect(editor.getByRole('button',{name:'移除人工关联：项目使用',exact:true})).toBeVisible();
 listFails=true;
 await editor.getByRole('button',{name:'刷新关联',exact:true}).click();
 await expect(editor.getByRole('alert')).toContainText('模拟读取失败');
 await expect(editor.getByRole('button',{name:'移除人工关联：项目使用',exact:true})).toBeVisible();
 listFails=false;
 await editor.getByRole('button',{name:'重新读取',exact:true}).click();
 await expect(editor.getByRole('alert')).toHaveCount(0);
 fs.mkdirSync('test-results',{recursive:true});
 await editor.scrollIntoViewIfNeeded();
 await page.screenshot({path:'test-results/relations-desktop.png',fullPage:true});
 await editor.getByRole('button',{name:'移除人工关联：项目使用',exact:true}).click();
 await expect(editor.getByRole('button',{name:'移除人工关联：项目使用',exact:true})).toHaveCount(0);
 await expect(page.locator('.relation-row').filter({hasText:'扫描使用'})).toBeVisible();
 await page.setViewportSize({width:390,height:844});
 await page.evaluate(()=>{document.documentElement.dataset.theme='dark'});
 await editor.scrollIntoViewIfNeeded();
 await page.screenshot({path:'test-results/relations-mobile-dark.png',fullPage:true});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 offline=true;
 await expect(editor.getByText('本地服务离线，人工关联暂不可修改。',{exact:true})).toBeVisible({timeout:10000});
 await expect(editor.getByRole('button',{name:'保存人工关联',exact:true})).toBeDisabled();
 assert.deepEqual(errors,[]);
 assert(writes.every(item=>item.path.startsWith('/api/relation/')||['/api/assistant/list','/api/action/list','/api/mcp-action/list'].includes(item.path)));
 console.log('PASS mocked relation search/add/remove, parent busy, missing endpoint, refresh failure retains rows, automatic edge survives, desktop/mobile-dark, offline guard; no real writes');
}finally{await browser.close()}
