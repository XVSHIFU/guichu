import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';

// Synthetic inventory plus intercepted POST requests: never edits a real config.
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const page=await browser.newPage({viewport:{width:1304,height:884},reducedMotion:'reduce'});
const object={id:'mock-codex-mcp',kind:'mcp',name:'Mock standalone MCP',scope:'codex',source:'用户配置',path:'C:/mock/.codex/config.toml',enabled:true,status:'配置启用',description:'Mock fixture only'};
const errors=[],writes=[];
let actions=[],conflict=false,offline=false;
page.on('pageerror',error=>errors.push(error.message));
await page.route('**/api/**',async route=>{
 const request=route.request(),path=new URL(request.url()).pathname;
 if(request.method()!=='POST'){
  if(path==='/api/state'){
   if(offline)return route.abort();
   const response=await route.fetch(),state=await response.json();
   state.data.objects=[object,...state.data.objects.filter(item=>item.id!==object.id)];
   return route.fulfill({json:state});
  }
  return route.continue();
 }
 const body=request.postDataJSON();writes.push({path,body});let result;
 if(path==='/api/assistant/list')result={sessions:[]};
 else if(path==='/api/action/list')result={actions:[]};
 else if(path==='/api/mcp-action/list')result={actions};
 else if(path==='/api/mcp-action/propose'){
  assert.equal(body.object_id,object.id);assert.equal(typeof body.enabled,'boolean');assert.match(body.request_id,/^[\da-f-]{36}$/i);
  const action={id:'mock-config-'+actions.length,revision:1,object:{id:object.id,name:object.name},path:object.path,backup_location:'C:/mock/backups/config-'+actions.length+'.toml',before_enabled:null,after_enabled:body.enabled,state:'pending'};
  actions=[action,...actions];result={action};
 }else if(path==='/api/mcp-action/confirm'||path==='/api/mcp-action/restore'){
  const action=actions.find(item=>item.id===body.id);assert(action);assert.equal(body.revision,action.revision);
  if(conflict){action.state=path.endsWith('restore')?'restore_conflict':'conflict';return route.fulfill({status:409,json:{error:'配置已被其他操作修改，请重新生成提案。',action}})}
  action.state=path.endsWith('restore')?'restored':'applied';action.receipt={backup_path:action.backup_location};result={action};
 }else return route.fulfill({status:400,json:{error:'Unexpected mocked write: '+path}});
 return route.fulfill({json:result});
});
try{
 await page.goto('http://127.0.0.1:8765');
 await page.getByRole('button',{name:'技能与连接',exact:false}).click();
 await page.getByLabel('搜索当前列表').fill(object.name);
 await page.locator('.object-row').filter({hasText:object.name}).click();
 await page.locator('.object-preview').click();
 await page.getByRole('button',{name:'操作',exact:true}).click();
 const panel=page.locator('.mcp-action-panel');
 await panel.getByRole('button',{name:'停用',exact:true}).click();
 await panel.getByRole('button',{name:'生成配置提案',exact:true}).click();
 await expect(panel.getByLabel('MCP 配置变更预览')).toContainText('默认启用（未设置）');
 await expect(panel.getByLabel('MCP 配置变更预览')).toContainText(object.path);
 await expect(panel.getByLabel('MCP 配置变更预览')).toContainText('C:/mock/backups/');
 assert.equal(writes.filter(item=>item.path.endsWith('/confirm')).length,0);
 await page.screenshot({path:'test-results/mcp-action-preview.png',fullPage:true});
 await panel.getByRole('button',{name:'确认修改配置',exact:true}).click();
 await expect(panel.getByRole('button',{name:'恢复原配置',exact:true})).toBeVisible();
 await panel.getByRole('button',{name:'恢复原配置',exact:true}).click();
 await expect(panel.getByText('已恢复执行前的配置；当前 Codex 会话可能仍需重新加载。',{exact:true})).toBeVisible();
 await panel.getByRole('button',{name:'启用',exact:true}).click();
 await panel.getByRole('button',{name:'生成配置提案',exact:true}).click();
 conflict=true;
 await panel.getByRole('button',{name:'确认修改配置',exact:true}).click();
 await expect(panel.getByRole('alert')).toContainText('配置已被其他操作修改');
 await expect(panel.locator('.mcp-action-heading')).toContainText('配置冲突');
 await page.screenshot({path:'test-results/mcp-action-conflict.png',fullPage:true});
 actions[0].state='interrupted';actions[0].receipt={backup_path:actions[0].backup_location};actions[0].observed_state='matches_after';conflict=false;
 await panel.getByRole('button',{name:'刷新记录',exact:true}).click();
 await expect(panel.getByText('当前配置与拟议修改一致。',{exact:true})).toBeVisible();
 await expect(panel.getByRole('button',{name:'恢复原配置',exact:true})).toBeVisible();
 await panel.getByRole('button',{name:'恢复原配置',exact:true}).click();
 await expect(panel.getByText('已恢复执行前的配置；当前 Codex 会话可能仍需重新加载。',{exact:true})).toBeVisible();
 offline=true;
 await expect(panel.getByText('本地服务离线，配置修改与恢复暂不可用。',{exact:true})).toBeVisible({timeout:10000});
 await expect(panel.getByRole('button',{name:'生成配置提案',exact:true})).toBeDisabled();
 assert.deepEqual(errors,[]);
 assert(writes.every(item=>item.path.startsWith('/api/mcp-action/')||['/api/action/list','/api/assistant/list'].includes(item.path)));
 console.log('PASS mocked MCP preview → confirm → restore, conflict, interrupted receipt recovery/observed state, offline guard; no real config writes');
}finally{await browser.close()}
