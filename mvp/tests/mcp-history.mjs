import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';

// All writes are intercepted. The historical object is absent from live inventory.
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const page=await browser.newPage({viewport:{width:1304,height:884},reducedMotion:'reduce'});
const object={id:'removed-historical-mcp',name:'已移除的测试 MCP'};
let actions=[{id:'history-applied',revision:1,object,path:'C:/mock/.codex/config.toml',state:'applied',before_enabled:true,after_enabled:false,created_at:'2026-10-03T01:00:00Z',backup_location:'C:/mock/backups/old.toml',receipt:{backup_path:'C:/mock/backups/old.toml'}},{id:'history-pending',revision:1,object:{id:'removed-pending',name:'已移除的旧提案'},path:'C:/mock/.codex/config.toml',state:'pending',before_enabled:true,after_enabled:false}];
const writes=[],errors=[];
page.on('pageerror',error=>errors.push(error.message));
await page.route('**/api/**',async route=>{
 const request=route.request(),path=new URL(request.url()).pathname;
 if(request.method()!=='POST'){
  if(path==='/api/state'){const response=await route.fetch(),state=await response.json();state.data.objects=[];state.data.relations=[];return route.fulfill({json:state})}
  return route.continue();
 }
 const body=request.postDataJSON();writes.push({path,body});let result;
 if(path==='/api/mcp-action/list')result={actions};
 else if(path==='/api/mcp-action/restore'){assert.equal(body.id,'history-applied');assert.equal(body.revision,1);actions=actions.map(item=>item.id===body.id?{...item,state:'restored'}:item);result={action:actions[0]}}
 else if(path==='/api/assistant/list')result={sessions:[]};
 else if(path.endsWith('/list'))result={actions:[],tasks:[]};
 else return route.fulfill({status:400,json:{error:'Unexpected mocked write: '+path}});
 return route.fulfill({json:result});
});
try{
 await page.goto('http://127.0.0.1:8765');
 await page.getByRole('button',{name:'变化记录',exact:false}).click();
 const history=page.getByRole('region',{name:'配置操作历史',exact:true});
 await history.locator('.mcp-global-record').filter({hasText:object.name}).click();
 await expect(history.getByRole('button',{name:'恢复原配置',exact:true})).toBeVisible();
 await expect(history.getByRole('button',{name:'生成配置提案',exact:true})).toHaveCount(0);
 await expect(history.getByRole('button',{name:'确认修改配置',exact:true})).toHaveCount(0);
 await page.screenshot({path:'test-results/mcp-history-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:'test-results/mcp-history-mobile.png',fullPage:true});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
 await history.getByRole('button',{name:'恢复原配置',exact:true}).click();
 await expect(history.getByText('已恢复执行前的配置；当前 Codex 会话可能仍需重新加载。',{exact:true})).toBeVisible();
 await history.locator('.mcp-global-record').filter({hasText:'已移除的旧提案'}).click();
 await expect(history.getByLabel('MCP 配置变更预览')).toContainText('待确认');
 await expect(history.getByRole('button',{name:'确认修改配置',exact:true})).toHaveCount(0);
 await expect(history.getByRole('button',{name:'恢复原配置',exact:true})).toHaveCount(0);
 assert.equal(writes.filter(item=>item.path.endsWith('/restore')).length,1);
 assert.equal(writes.filter(item=>/\/(confirm|propose)$/.test(item.path)).length,0);
 assert.deepEqual(errors,[]);
 console.log('PASS global MCP history: absent object snapshot restoration, pending cannot apply, desktop/mobile; all writes mocked');
}finally{await browser.close()}
