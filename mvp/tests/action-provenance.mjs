import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';

// All mutations are intercepted, including configuration and cleanup actions.
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const page=await browser.newPage({viewport:{width:1304,height:884},reducedMotion:'reduce'});
const mcp={id:'origin-mcp',name:'来源测试 MCP',kind:'mcp',scope:'codex',source:'用户配置',path:'C:\\mock\\config.toml'};
const directory={id:'origin-directory',name:'来源测试目录',kind:'directory',path:'C:\\mock\\recycle',source:'测试'};
const sessions=[{id:'source-mcp',title:'MCP 讨论',mode:'readonly',target:mcp,draft:'',plan:null,accepted:false,active_run_id:'origin-run',messages:[{id:'reply',role:'assistant',mode:'readonly',run_id:'origin-run',text:'只读分析结果。'}]},{id:'source-directory',title:'目录讨论',mode:'readonly',target:directory,draft:'',plan:null,accepted:false,messages:[]}];
const actions=[],writes=[],errors=[];let directoryGone=false,sourceDeleted=false;
page.on('pageerror',error=>errors.push(error.message));
await page.addInitScript(()=>localStorage.setItem('desk-assistant-session','source-mcp'));
await page.route('**/api/**',async route=>{
 const req=route.request(),path=new URL(req.url()).pathname;
 if(req.method()!=='POST'){
  if(path==='/api/state'){const response=await route.fetch(),state=await response.json();state.data.objects.push(mcp,...(directoryGone?[]:[directory]));return route.fulfill({json:state})}
  return route.continue();
 }
 const body=req.postDataJSON();writes.push({path,body});let result;
 if(path==='/api/model/settings')result={config:{endpoint:'https://mock.invalid',model:'mock-model'}};
 else if(path==='/api/assistant/list')result={sessions:sessions.filter(s=>!sourceDeleted||s.id!=='source-directory')};
 else if(path==='/api/assistant/get'){
  if(sourceDeleted&&body.id==='source-directory')return route.fulfill({status:404,json:{error:'会话不存在'}});
  result={session:sessions.find(s=>s.id===body.id)};
 }else if(path==='/api/assistant/actions')result={actions:actions.filter(a=>a.origin?.session_id===body.id)};
 else if(path==='/api/run/get'){sessions[0].active_run_id=null;result={run:{id:'origin-run',session_id:'source-mcp',target:mcp,status:'succeeded',answer:'只读分析结果。',usage:{total_tokens:12}},events:[{seq:1,type:'completed'}]};}
 else if(/^\/api\/(action|mcp-action|cleanup)\/list$/.test(path))result={actions:actions.filter(a=>a.family===path.split('/')[2])};
 else if(/^\/api\/(action|mcp-action|cleanup)\/propose$/.test(path)){
  const family=path.split('/')[2],object=body.object_id===mcp.id?mcp:directory,source=sessions.find(s=>s.id===body.origin?.session_id);assert(source);
  if(object===mcp)assert.equal(body.origin.run_id,'origin-run');else assert.equal(body.origin.run_id,undefined);
  const action={id:'origin-action-'+actions.length,family,revision:1,state:'pending',object:{...object},path:object.path,origin:{...body.origin,title:source.title,mode:source.mode,object_id:object.id},kind:body.kind,before:null,after:{decision:body.decision},before_enabled:null,after_enabled:body.enabled,backup_location:'C:\\mock\\backup',preview:{path:object.path,files:1,directories:1,bytes:8,usage_check:'complete'}};actions.push(action);result={action};
 }else if(/^\/api\/(action|mcp-action|cleanup)\/confirm$/.test(path)){
  const action=actions.find(a=>a.id===body.id);assert(action);action.state=action.family==='cleanup'?'recycled':'applied';if(action.family==='cleanup'){assert.equal(body.acknowledge,true);directoryGone=true;}result={action};
 }else return route.fulfill({status:400,json:{error:'Unexpected mocked write '+path}});
 return route.fulfill({json:result});
});
try{
 await page.goto('http://127.0.0.1:8765');await page.getByRole('button',{name:'归处助手',exact:true}).click();await page.getByText('分析完成',{exact:true}).waitFor();
 await page.getByRole('tab',{name:'对象',exact:true}).click();await page.getByRole('button',{name:'预览并确认对象操作',exact:true}).click();
 const mcpPanel=page.locator('.mcp-action-panel');await mcpPanel.getByRole('button',{name:'停用',exact:true}).click();await mcpPanel.getByRole('button',{name:'生成配置提案',exact:true}).click();await expect(mcpPanel).toContainText('来源对话：MCP 讨论');await mcpPanel.getByRole('button',{name:'确认修改配置',exact:true}).click();await mcpPanel.getByRole('button',{name:'返回来源对话',exact:true}).click();
 await page.getByRole('tab',{name:/操作/}).click();const receipts=page.getByRole('region',{name:'关联操作记录'});await page.getByRole('tab',{name:/操作/}).click();await expect(receipts).toContainText('MCP 配置 · 已执行');
 await page.getByRole('tab',{name:'对象',exact:true}).click();await page.getByRole('button',{name:'预览并确认对象操作',exact:true}).click();
 const notePanel=page.locator('.action-panel');await notePanel.getByRole('button',{name:'保留',exact:true}).click();await notePanel.getByRole('button',{name:'生成标记提案',exact:true}).click();await expect(notePanel).toContainText('来源对话：MCP 讨论');await notePanel.getByRole('button',{name:'确认更新标记',exact:true}).click();await notePanel.getByRole('button',{name:'返回来源对话',exact:true}).click();await page.getByRole('tab',{name:/操作/}).click();await expect(receipts).toContainText('保留决定 · 已执行');
 await receipts.screenshot({path:'test-results/assistant-action-provenance.png'});
 await page.getByRole('button',{name:/历史对话/}).click();await page.locator('.assistant-history-open').filter({hasText:'目录讨论'}).click();await page.getByRole('tab',{name:'对象',exact:true}).click();await page.getByRole('button',{name:'预览并确认对象操作',exact:true}).click();
 const cleanup=page.getByRole('region',{name:'目录回收',exact:true});await cleanup.getByRole('button',{name:'预览回收范围',exact:true}).click();await expect(cleanup).toContainText('来源对话：目录讨论');await cleanup.getByRole('checkbox').check();await cleanup.getByRole('button',{name:'确认移到回收站',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
 await page.getByRole('button',{name:'变化记录',exact:true}).click();const history=page.getByRole('region',{name:'清理操作记录',exact:true});await history.getByText('查看全部清理操作',{exact:true}).click();await history.getByRole('button',{name:/来源测试目录 · 目录回收/}).click();await history.getByRole('button',{name:'返回来源对话',exact:true}).click();await page.getByRole('tab',{name:/操作/}).click();await expect(receipts).toContainText('目录回收 · 已移到回收站');
 sourceDeleted=true;await page.getByRole('button',{name:'变化记录',exact:true}).click();await history.getByText('查看全部清理操作',{exact:true}).click();await history.getByRole('button',{name:/来源测试目录 · 目录回收/}).click();await history.getByRole('button',{name:'返回来源对话',exact:true}).click();await expect(page.getByRole('alert')).toContainText('来源会话已删除或不存在');
 assert.equal(writes.filter(item=>item.path==='/api/assistant/create').length,0);assert.deepEqual(errors,[]);
 console.log('PASS mocked three action families preserve origin, terminal run identity, reverse navigation, conversation receipts, deleted object/source history without replacement; no real mutations');
}finally{await browser.close()}
