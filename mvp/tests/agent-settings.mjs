import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';

const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const page=await browser.newPage({viewport:{width:1304,height:884},reducedMotion:'reduce'});
let servers=[],instructions='';const writes=[],errors=[];
page.on('pageerror',error=>errors.push(error.message));
const tools=[{name:'read_fixture',description:'读取临时样例中的固定摘要。',inputSchema:{type:'object'},readOnlyHint:true},{name:'write_fixture',description:'未声明只读的样例工具。',inputSchema:{type:'object'},readOnlyHint:false}];
await page.route('**/api/**',async route=>{
 const req=route.request(),path=new URL(req.url()).pathname;
 if(req.method()!=='POST')return route.continue();
 const body=req.postDataJSON();let result;
 if(path==='/api/agent/preferences'){if('instructions'in body){instructions=body.instructions.trim();writes.push(path)}result={preferences:{instructions}}}
 else if(path==='/api/mcp-client/list')result={servers};
 else if(path==='/api/mcp-client/save'){
  assert.equal(body.acknowledge_execution,true);assert(!('revision'in body));assert(!('tools'in body));
  const record={...body,id:body.id||'a'.repeat(32),tools:servers[0]?.tools||[],revision:(servers[0]?.revision||0)+1};servers=[record];result={server:record};writes.push(path);
 }else if(path==='/api/mcp-client/discover'){
  assert.equal(body.acknowledge_execution,true);servers=[{...servers[0],enabled:false,allowed_tools:[],tools}];result={server:servers[0],tools};writes.push(path);
 }else if(path==='/api/mcp-client/delete'){assert.equal(body.id,servers[0].id);servers=[];result={deleted:true};writes.push(path)}
 else if(['/api/model/catalog','/api/source/list','/api/assistant/list'].includes(path))return route.continue();
 else return route.fulfill({status:400,json:{error:'Unexpected mock request '+path}});
 return route.fulfill({json:result});
});
try{
 await page.goto('http://127.0.0.1:8765');
 await page.locator('.sidebar').getByRole('button',{name:'设置',exact:true}).click();
 await page.getByRole('tab',{name:'助手',exact:false}).click();
 const section=page.locator('.agent-settings');
 await section.getByLabel('使用偏好',{exact:false}).fill('待保存的独立偏好');
 await section.getByRole('button',{name:'添加连接',exact:true}).click();
 await section.getByLabel('连接名称',{exact:true}).fill('临时只读测试服务');
 await section.getByLabel('可执行程序',{exact:true}).fill('C:/mock/python.exe');
 await section.getByLabel('启动参数',{exact:false}).fill('C:/mock/fixture.py');
 await section.getByLabel('工作目录',{exact:true}).fill('C:/mock');
 const acknowledgement=section.getByRole('checkbox',{name:'我信任此程序',exact:false});
 await acknowledgement.check();await section.getByRole('button',{name:'保存连接',exact:true}).click();
 await expect(section.getByLabel('使用偏好',{exact:false})).toHaveValue('待保存的独立偏好');
 await section.getByRole('button',{name:'编辑',exact:true}).click();await acknowledgement.check();
 await section.getByRole('button',{name:'读取已保存连接的工具',exact:true}).click();
 await section.getByRole('checkbox',{name:'read_fixture',exact:false}).check();
 await expect(section.getByRole('checkbox',{name:'write_fixture',exact:false})).toBeDisabled();
 await section.getByRole('checkbox',{name:'允许归处助手在会话中调用所选工具',exact:true}).check();
 await page.screenshot({path:'test-results/agent-settings-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:'test-results/agent-settings-mobile.png',fullPage:true});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await section.getByRole('button',{name:'保存连接',exact:true}).click();
 await expect(section.getByText('已允许助手调用 · 1 个工具',{exact:true})).toBeVisible();
 await section.getByRole('button',{name:'编辑',exact:true}).click();await acknowledgement.check();
 await section.getByLabel('可执行程序',{exact:true}).fill('C:/mock/changed.exe');
 await expect(acknowledgement).not.toBeChecked();await acknowledgement.check();
 await expect(section.getByRole('button',{name:'读取已保存连接的工具',exact:true})).toBeDisabled();
 await section.getByRole('button',{name:'取消',exact:true}).click();
 await section.getByRole('button',{name:'保存偏好',exact:true}).click();assert.equal(instructions,'待保存的独立偏好');
 await section.getByRole('button',{name:'移除连接 临时只读测试服务',exact:true}).click();
 await section.getByRole('button',{name:'确认移除',exact:true}).click();
 await expect(section.getByText('还没有连接。',{exact:false})).toBeVisible();
 await page.setViewportSize({width:1304,height:884});
 await section.getByRole('button',{name:'添加连接',exact:true}).click();
 await section.getByLabel('连接方式',{exact:true}).selectOption('streamable-http');
 await section.getByLabel('连接名称',{exact:true}).fill('远程文档服务');
 await section.getByLabel('服务地址',{exact:true}).fill('https://example.com/mcp');
 await section.getByLabel('访问令牌',{exact:false}).fill('fixture-not-a-real-token');
 await expect(section.getByLabel('访问令牌',{exact:false})).toHaveAttribute('type','password');
 await section.getByRole('checkbox',{name:'我信任此服务',exact:false}).check();
 await page.screenshot({path:'test-results/agent-settings-remote-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:'test-results/agent-settings-remote-mobile.png',fullPage:true});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await section.getByRole('button',{name:'保存连接',exact:true}).click();
 assert.equal(servers[0].transport,'streamable-http');assert.equal(servers[0].url,'https://example.com/mcp');
 assert.deepEqual(errors,[]);assert.equal(writes.filter(x=>x.endsWith('/discover')).length,1);assert.equal(writes.filter(x=>x.endsWith('/save')).length,3);
 console.log('PASS mocked registration/discovery/allowlist/enable/delete/preferences, dirty-command guard, draft preservation, mobile; no real MCP started');
}finally{await browser.close()}
