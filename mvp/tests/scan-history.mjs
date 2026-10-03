import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';

// Mock scan history and every POST: no inventory scan starts on this machine.
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const page=await browser.newPage({viewport:{width:1304,height:884},reducedMotion:'reduce'});
const errors=[],writes=[];
let offline=false,running=false;
const tasks=[
 {id:'partial',status:'partial',started_at:'2026-10-03T10:00:00+08:00',finished_at:'2026-10-03T10:00:03+08:00',object_count:12,issue_count:1,sources:[{id:'tools',status:'ok'},{id:'skills',status:'ok'},{id:'config',status:'failed'}],error:'模拟来源读取失败'},
 {id:'failed',status:'failed',started_at:'2026-10-03T09:00:00+08:00',finished_at:'2026-10-03T09:00:02+08:00',error:'模拟检查失败'},
 {id:'interrupted',status:'interrupted',started_at:'2026-10-03T08:00:00+08:00',finished_at:'2026-10-03T08:00:01+08:00'},
 {id:'ok',status:'succeeded',started_at:'2026-10-03T07:00:00+08:00',finished_at:'2026-10-03T07:00:02+08:00',object_count:10}
];
page.on('pageerror',error=>errors.push(error.message));
await page.route('**/api/**',async route=>{
 const request=route.request(),path=new URL(request.url()).pathname;
 if(request.method()!=='POST'){
  if(path==='/api/state'){
   if(offline)return route.abort();
   const response=await route.fetch(),state=await response.json();state.scan_history=tasks;state.scan={running,error:null,...(running?{task:{id:'new',status:'running',started_at:tasks[0].started_at}}:{})};return route.fulfill({json:state});
  }
  return route.continue();
 }
 writes.push(path);
 if(path==='/api/assistant/list')return route.fulfill({json:{sessions:[]}});
 if(path==='/api/scan'){running=true;tasks.unshift({id:'new',status:'running',started_at:new Date().toISOString()});return route.fulfill({json:{ok:true}})}
 return route.fulfill({status:400,json:{error:'Unexpected mocked write '+path}});
});
try{
 await page.goto('http://127.0.0.1:8765');await page.getByRole('button',{name:'变化记录',exact:true}).click();
 const history=page.getByRole('region',{name:'检查任务'});
 await expect(history.getByText('部分完成',{exact:true})).toBeVisible();
 await expect(history).toContainText('未完整读取的来源会保留已有记录');
 await expect(history).toContainText('12 个对象');await expect(history).toContainText('1 项未完成检查');
 await expect(history.getByText('检查失败',{exact:true})).toBeVisible();
 await expect(history.getByText('检查中断',{exact:true})).toBeVisible();
 await expect(history.getByText('检查完成',{exact:true})).toBeVisible();
 await page.screenshot({path:'test-results/scan-history.png',fullPage:true});
 await history.getByRole('button',{name:'重新检查',exact:true}).click();
 await expect(history.getByText('正在检查',{exact:true})).toBeVisible({timeout:10000});
 await expect(history.getByRole('button',{name:'重新检查',exact:true})).toBeDisabled();
 assert.equal(writes.filter(path=>path==='/api/scan').length,1);
 running=false;tasks[0]={...tasks[0],status:'succeeded',finished_at:new Date().toISOString()};
 await expect(history.getByRole('button',{name:'重新检查',exact:true})).toBeEnabled({timeout:10000});
 offline=true;
 await expect(history.getByText('本地服务离线，当前显示最近收到的检查记录。',{exact:true})).toBeVisible({timeout:10000});
 await expect(history.getByRole('button',{name:'重新检查',exact:true})).toBeDisabled();
 assert.deepEqual(errors,[]);assert(writes.every(path=>['/api/scan','/api/assistant/list'].includes(path)));
 console.log('PASS mocked history status/time/summary, partial retained sources, retry callback, running/offline guard; no real inventory scan');
}finally{await browser.close()}
