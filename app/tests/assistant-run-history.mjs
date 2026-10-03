import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';

const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const page=await browser.newPage({viewport:{width:1304,height:884},reducedMotion:'reduce'});
const target={id:'history-target',name:'历史目标',kind:'mcp',scope:'codex',source:'用户配置',path:'C:\\mock\\config.toml'};
const sessions=['failed','cancelled','succeeded'].map(status=>({id:'session-'+status,title:'历史 '+status,mode:'readonly',target,draft:'',plan:null,accepted:false,messages:[{id:'reply-'+status,role:'assistant',mode:'readonly',run_id:'run-'+status,text:status==='succeeded'?'完整历史回答。':'保留的部分回答。'}]}));
sessions[2].messages.unshift({id:'older-reply',role:'assistant',mode:'readonly',run_id:'run-old-failed',text:'较早失败的部分回答。'});
const gets=[],errors=[];
page.on('pageerror',error=>errors.push(error.message));
await page.addInitScript(()=>localStorage.setItem('desk-assistant-session','session-failed'));
await page.route('**/api/**',async route=>{
 const request=route.request(),path=new URL(request.url()).pathname;
 if(request.method()!=='POST'){
  if(path==='/api/state'){const response=await route.fetch(),state=await response.json();state.data.objects.push(target);return route.fulfill({json:state})}
  return route.continue();
 }
 const body=request.postDataJSON();let result;
 if(path==='/api/model/settings')result={config:{endpoint:'https://mock.invalid',model:'mock-model'}};
 else if(path==='/api/assistant/list')result={sessions};
 else if(path==='/api/assistant/get')result={session:sessions.find(s=>s.id===body.id)};
 else if(path==='/api/assistant/actions')result={actions:[]};
 else if(path==='/api/assistant/update'){const session=sessions.find(s=>s.id===body.id);session.draft=body.draft;result={session};}
 else if(path==='/api/run/get'){
  gets.push(body);const historical=body.id==='run-old-failed',status=historical?'failed':body.id.replace('run-','');const events=Array.from({length:status==='failed'?601:1},(_,i)=>({seq:i+1,type:'tool_finished',name:status+'-tool-'+(i+1)}));
  if(status==='failed')await new Promise(resolve=>setTimeout(resolve,120));
  result={run:{id:body.id,session_id:historical?'session-succeeded':'session-'+status,target,status,answer:status==='succeeded'?'完整历史回答。':'保留的部分回答。',error:status==='failed'?'模拟模型超时':status==='cancelled'?'任务已取消':null,usage:{total_tokens:status==='failed'?45:20}},events:events.filter(event=>event.seq>(body.after||0)).slice(0,500)};
 }else return route.fulfill({status:400,json:{error:'Unexpected mocked write '+path}});
 return route.fulfill({json:result});
});
try{
 await page.goto('http://127.0.0.1:8765');await page.getByRole('button',{name:'归处助手',exact:true}).click();
 await page.getByLabel('给助手的请求').fill('恢复运行信息时保留的新草稿');
 const run=page.getByRole('region',{name:'只读运行状态'});
 await expect(run.getByText('分析失败',{exact:true})).toBeVisible();await expect(run).toContainText('模拟模型超时');await expect(run).toContainText('Token 用量：45');
 await run.getByRole('button',{name:'查看轨迹'}).click();await expect(page.getByText('轨迹步骤 · 601',{exact:true})).toBeVisible();await expect(page.locator('.trajectory-step-title').filter({hasText:'failed-tool-601'})).toBeVisible();
 assert(gets.some(item=>item.id==='run-failed'&&item.after===500));
 await expect(page.getByLabel('给助手的请求')).toHaveValue('恢复运行信息时保留的新草稿');
 await page.getByRole('button',{name:/历史对话/}).click();await page.locator('.assistant-history-open').filter({hasText:'历史 cancelled'}).click();
 await expect(run.getByText('已取消',{exact:true})).toBeVisible();await expect(run).toContainText('任务已取消');await expect(run).not.toContainText('failed-tool-601');
 await page.getByRole('button',{name:/历史对话/}).click();await page.locator('.assistant-history-open').filter({hasText:'历史 succeeded'}).click();
 await expect(run.getByText('分析完成',{exact:true})).toBeVisible();await expect(run).toContainText('Token 用量：20');await expect(run).not.toContainText('任务已取消');
 await page.getByRole('tab',{name:'对象',exact:true}).click();await expect(page.getByRole('button',{name:'预览并确认对象操作',exact:true})).toBeEnabled();
 await page.locator('.assistant-message').filter({hasText:'较早失败的部分回答。'}).getByRole('button',{name:'查看轨迹',exact:true}).click();await expect(run.getByText('分析失败',{exact:true})).toBeVisible();await expect(page.getByRole('tabpanel',{name:'轨迹',exact:true})).toContainText('轨迹步骤 · 601');assert(gets.some(item=>item.id==='run-old-failed'&&item.after===500));await page.getByRole('button',{name:'查看最新轨迹',exact:true}).click();await expect(run.getByText('分析完成',{exact:true})).toBeVisible();
 assert.deepEqual(errors,[]);
 console.log('PASS mocked terminal failed/cancelled/succeeded run restore, >500 event drain, scope isolation, usage/error recovery, draft preservation');
}finally{await browser.close()}
