import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';

// All browse/size writes are intercepted; this test never scans a real directory.
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const page=await browser.newPage({viewport:{width:1304,height:884},reducedMotion:'reduce'});
const root='C:\\mock-size',child=root+'\\child',tasks=[],writes=[],errors=[];
let partial=false;
page.on('pageerror',error=>errors.push(error.message));
await page.route('**/api/**',async route=>{
 const request=route.request(),path=new URL(request.url()).pathname;
 if(request.method()!=='POST'){
  if(path==='/api/state'){const response=await route.fetch(),state=await response.json();state.data.objects.push({id:'size-fixture',kind:'directory',name:'大小统计测试目录',path:root,description:'仅供模拟测试',source:'测试'});return route.fulfill({json:state})}
  return route.continue();
 }
 const body=request.postDataJSON();writes.push({path,body});let result;
 if(path==='/api/assistant/list')result={sessions:[]};
 else if(path==='/api/browse'){const isRoot=body.path.replace(/[\\]+$/,'')===root;result={path:body.path,parent:isRoot?'C:\\':root,entries:isRoot?[{name:'child',path:child,directory:true,link:false}]:[],directoryCount:isRoot?1:0,fileCount:0,total:isRoot?1:0,next:null};}
 else if(path==='/api/size/list')result={tasks};
 else if(path==='/api/size/start'){assert.match(body.request_id,/^[\da-f-]{36}$/i);const task={id:'mock-size-'+tasks.length,path:body.path,status:'running',bytes:2048,files:2,directories:1,errors:0,skipped:0,hardlinks:0,limit:null,created_at:new Date().toISOString(),updated_at:new Date().toISOString()};tasks.unshift(task);result={task};}
 else if(path==='/api/size/get'){const task=tasks.find(item=>item.id===body.id);assert(task);if(partial&&task.status==='running')Object.assign(task,{status:'partial',bytes:4096,files:4,errors:1,skipped:2,limit:'entries'});await new Promise(resolve=>setTimeout(resolve,180));result={task};}
 else if(path==='/api/size/cancel'){const task=tasks.find(item=>item.id===body.id);assert(task);task.status='cancelled';result={task};}
 else return route.fulfill({status:400,json:{error:'Unexpected mocked write '+path}});
 return route.fulfill({json:result});
});
try{
 await page.goto('http://127.0.0.1:8765');await page.getByRole('button',{name:'目录地图',exact:true}).click();
 await page.locator('.folder-main').filter({hasText:'大小统计测试目录'}).click();
 const panel=page.getByRole('region',{name:'目录大小统计'});
 await expect(panel.getByRole('button',{name:'统计目录大小',exact:true})).toBeEnabled();
 assert.equal(writes.filter(item=>item.path==='/api/size/start').length,0);
 await panel.getByRole('button',{name:'统计目录大小',exact:true}).click();
 await expect(panel.getByText('正在统计',{exact:true})).toBeVisible();
 await expect(panel.getByText('2,048 字节',{exact:true})).toBeVisible();
 await page.locator('.folder-main').filter({hasText:'child'}).click();
 await expect(page.locator('.directory-crumb code')).toHaveText(child);
 await expect(panel.getByRole('button',{name:'统计目录大小',exact:true})).toBeEnabled();
 await expect(panel.getByText('2,048 字节',{exact:true})).toHaveCount(0);
 partial=true;
 await page.getByRole('button',{name:'上一级',exact:true}).click();
 await expect(panel.getByText('部分结果',{exact:true})).toBeVisible();
 await expect(panel).toContainText('已达到条目数量限制');
 assert.equal(writes.filter(item=>item.path==='/api/size/start').length,1);
 await page.screenshot({path:'test-results/directory-size-partial.png',fullPage:true});
 partial=false;
 await panel.getByRole('button',{name:'重新统计',exact:true}).click();
 await panel.getByRole('button',{name:'停止统计',exact:true}).click();
 await expect(panel.getByText('已停止',{exact:true})).toBeVisible();
 await expect(panel.getByRole('button',{name:'重试统计',exact:true})).toBeEnabled();
 assert.equal(writes.filter(item=>item.path==='/api/size/start').length,2);
 assert.deepEqual(errors,[]);
 console.log('PASS mocked explicit start, progress, browse while running, path isolation/history resume, partial limit, retry/cancel; no real directory scan');
}finally{await browser.close()}
