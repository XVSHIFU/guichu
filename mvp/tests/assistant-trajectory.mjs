import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
try {
 const page=await browser.newPage({viewport:{width:1435,height:920},reducedMotion:'reduce'}),errors=[],writes=[];
 page.on('pageerror',e=>errors.push(e.message));
 let cancelled=false;
 const session={id:'trajectory-session',title:'核对工具与配置',mode:'readonly',draft:'',target:null,active_run_id:null,messages:[{id:'u1',role:'user',text:'hi'},{id:'a1',role:'assistant',mode:'readonly',run_id:'trajectory-run',text:'## 已核对清单\n\n已读取对象信息。一次工具调用未返回有效结果，建议先核对对象范围。'}]};
 let status='succeeded';
 const events=[{seq:1,type:'started',at:'2026-10-03T08:00:00Z'},{seq:2,type:'tool_started',name:'search_objects',at:'2026-10-03T08:00:01Z'},{seq:3,type:'tool_finished',name:'search_objects',ok:true,at:'2026-10-03T08:00:01.125Z'},{seq:4,type:'tool_started',name:'get_object',at:'2026-10-03T08:00:02Z'},{seq:5,type:'tool_finished',name:'get_object',ok:false,at:'2026-10-03T08:00:02.025Z'},{seq:6,type:'text',text:'已核对清单。',at:'2026-10-03T08:00:03Z'},{seq:7,type:'finished',status:'succeeded',at:'2026-10-03T08:00:04Z'}];
 await page.addInitScript(()=>{localStorage.setItem('desk-assistant-session','trajectory-session');localStorage.setItem('desk-appearance',JSON.stringify({palette:'pine',mode:'light'}));});
 await page.route('**/api/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname;if(req.method()!=='POST')return route.continue();const body=req.postDataJSON();writes.push(path);let result;
  if(path==='/api/model/settings')result={config:{endpoint:'https://mock.invalid',model:'mock'}};
  else if(path==='/api/assistant/list')result={sessions:[session]};
  else if(path==='/api/assistant/get')result={session};
  else if(path==='/api/assistant/update'){session.draft=body.draft;result={session};}
  else if(path==='/api/assistant/actions')result={actions:[]};
  else if(path==='/api/run/get')result={run:{id:'trajectory-run',session_id:session.id,status,model:'mock',provider_name:'测试连接',usage:{total_tokens:42}},events:events.filter(e=>e.seq>(body.after||0))};
  else if(path==='/api/run/cancel'){cancelled=true;status='cancelled';session.active_run_id=null;result={ok:true};}
  else return route.fulfill({status:400,json:{error:'Unexpected mocked request '+path}});
  return route.fulfill({json:result});
 });
 await page.goto('http://127.0.0.1:8765');await page.getByRole('button',{name:'归处助手',exact:true}).click();
 await page.getByRole('region',{name:'只读运行状态'}).getByRole('button',{name:'查看轨迹'}).click();
 const pane=page.getByRole('tabpanel',{name:'轨迹',exact:true});
 await expect(pane.getByText('轨迹步骤 · 5',{exact:true})).toBeVisible();
 await expect(pane.getByText('已完成 · 125 毫秒',{exact:true})).toBeVisible();
 await expect(pane.getByText('调用失败 · 25 毫秒',{exact:true})).toBeVisible();
 await page.getByLabel('给助手的请求').fill('查看轨迹时保留草稿');
 await pane.getByLabel('搜索轨迹').fill('get_object');await expect(pane.locator('.trajectory-ledger>li')).toHaveCount(1);await expect(pane.getByRole('status')).toContainText('匹配 1 项');
 await pane.getByLabel('搜索轨迹').fill('');await pane.getByRole('button',{name:'折叠工具调用',exact:true}).click();await expect(pane.locator('.trajectory-ledger>li')).toHaveCount(3);await pane.getByRole('button',{name:'展开工具调用',exact:true}).click();
 await pane.getByRole('button',{name:'折叠本次请求',exact:true}).click();await expect(pane.locator('.trajectory-ledger')).toBeHidden();await pane.getByRole('button',{name:'展开本次请求',exact:true}).click();
 await pane.getByRole('button',{name:'按记录时长排列',exact:true}).click();await expect(pane.getByLabel('真实记录时间带')).toBeVisible();
 const step=pane.locator('.trajectory-ledger').getByRole('button',{name:/搜索清单对象/});await step.click();
 await expect(pane).toContainText('未保存调用参数或结果正文');await expect(pane).toContainText('125 毫秒');
 await pane.getByText('查看原始记录',{exact:true}).click();await expect(pane.locator('pre')).toContainText('tool_finished');
 await pane.getByRole('button',{name:'返回轨迹'}).click();await expect(step).toBeFocused();
 const user=await page.locator('.assistant-message.user').boundingBox();assert(user.width<120,`hi bubble ${user.width}`);
 const spacing=await page.locator('.assistant-message.assistant').evaluate(el=>parseFloat(getComputedStyle(el).marginLeft));assert(spacing>=8&&spacing<=12);
 const sidebar=page.locator('.assistant-context');await page.getByLabel('给助手的请求').hover();const normal=await sidebar.evaluate(el=>getComputedStyle(el).backgroundColor);await sidebar.hover();const hover=await sidebar.evaluate(el=>getComputedStyle(el).backgroundColor);assert.notEqual(normal,hover);
 await page.getByLabel('给助手的请求').hover();await page.screenshot({path:'test-results/assistant-trajectory-1435.png'});
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:'test-results/assistant-trajectory-390-chat.png'});
 await page.getByRole('button',{name:'会话详情',exact:true}).click();await page.getByRole('tab',{name:'轨迹',exact:true}).click();
 await page.screenshot({path:'test-results/assistant-trajectory-390.png'});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await page.keyboard.press('Escape');await expect(page.getByRole('button',{name:'会话详情',exact:true})).toBeFocused();await expect(page.getByLabel('给助手的请求')).toHaveValue('查看轨迹时保留草稿');
 // Reload with a real-shaped active run; stopping remains a mocked API action.
 status='running';session.active_run_id='trajectory-run';events.splice(4);await page.setViewportSize({width:1435,height:920});await page.reload();await page.getByRole('button',{name:'归处助手',exact:true}).click();await expect(page.getByRole('button',{name:'停止分析'})).toBeVisible();await page.setViewportSize({width:390,height:844});
 await page.getByRole('region',{name:'只读运行状态'}).getByRole('button',{name:'查看轨迹'}).click();await expect(page.getByRole('tabpanel',{name:'轨迹'})).toContainText('正在调用');await page.keyboard.press('Escape');await page.getByRole('button',{name:'停止分析'}).click();
 await expect.poll(()=>cancelled).toBe(true);assert(!writes.includes('/api/run/start'));assert.deepEqual(errors,[]);
 console.log('PASS trajectory pairing/details/focus/draft/active cancel, hi width, reply inset, context hover and 1435/390 screenshots; no model calls');
}finally{await browser.close()}
