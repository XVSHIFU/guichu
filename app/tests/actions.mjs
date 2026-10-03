import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';

// Only GET requests reach the local service. All writes are mocked.
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const page=await browser.newPage({viewport:{width:1304,height:884},reducedMotion:'reduce'});
const errors=[],writes=[];
let actions=[],conflict=false,offline=false;
page.on('pageerror',error=>errors.push(error.message));
await page.route('**/api/**',async route=>{
 const req=route.request(),path=new URL(req.url()).pathname;
 if(req.method()!=='POST')return offline&&path==='/api/state'?route.abort():route.continue();
 const body=req.postDataJSON();writes.push({path,body});
 let result;
 if(path==='/api/assistant/list')result={sessions:[]};
 else if(path==='/api/action/list')result={actions};
 else if(path==='/api/action/propose'){
  assert.match(body.request_id,/^[\da-f-]{36}$/i);
  const action={id:'mock-action-'+actions.length,revision:1,object:{id:body.object_id,name:'测试对象'},before:null,after:{decision:body.decision,body:''},state:'pending'};
  actions=[action,...actions];result={action};
 }else if(path==='/api/action/confirm'||path==='/api/action/restore'){
  const action=actions.find(item=>item.id===body.id);assert(action);assert.equal(body.revision,action.revision);
  if(conflict){action.state=path.endsWith('restore')?'restore_conflict':'conflict';return route.fulfill({status:409,json:{error:'当前标记已改变，请重新生成提案。'}})}
  action.state=path.endsWith('restore')?'restored':'applied';result={action};
 }else return route.fulfill({status:400,json:{error:'Unexpected mocked write: '+path}});
 return route.fulfill({json:result});
});
try{
 await page.goto('http://127.0.0.1:8765');
 await page.locator('.agent-row').first().click();
 await page.locator('.object-preview').click();
 await page.getByRole('button',{name:'操作',exact:true}).click();
 const panel=page.locator('.action-panel');
 await panel.getByRole('button',{name:'保留',exact:true}).click();
 await panel.getByRole('button',{name:'生成标记提案',exact:true}).click();
 await expect(panel.getByLabel('标记变更预览')).toContainText('未标记');
 await expect(panel.getByLabel('标记变更预览')).toContainText('保留');
 assert.equal(writes.filter(item=>item.path.endsWith('/confirm')).length,0);
 await page.screenshot({path:'test-results/action-preview.png',fullPage:true});
 await panel.getByRole('button',{name:'确认更新标记',exact:true}).click();
 await expect(panel.getByRole('button',{name:'恢复执行前标记',exact:true})).toBeVisible();
 await panel.getByRole('button',{name:'恢复执行前标记',exact:true}).click();
 await expect(panel.getByText('已恢复执行前的工作台标记。',{exact:true})).toBeVisible();
 await panel.getByRole('button',{name:'待确认',exact:true}).click();
 await panel.getByRole('button',{name:'生成标记提案',exact:true}).click();
 conflict=true;
 await panel.getByRole('button',{name:'确认更新标记',exact:true}).click();
 await expect(panel.getByRole('alert')).toContainText('当前标记已改变');
 await expect(panel.locator('.action-preview-heading')).toContainText('执行冲突');
 await page.screenshot({path:'test-results/action-conflict.png',fullPage:true});
 offline=true;
 await expect(panel.getByText('本地服务离线，标记修改与恢复暂不可用。',{exact:true})).toBeVisible({timeout:10000});
 await expect(panel.getByRole('button',{name:'生成标记提案',exact:true})).toBeDisabled();
 assert.deepEqual(errors,[]);
 assert(writes.every(item=>item.path.startsWith('/api/action/')||item.path==='/api/assistant/list'));
 console.log('PASS mocked preview → confirm → restore, conflict refresh, offline guard; no real workspace marker writes');
}finally{await browser.close()}
