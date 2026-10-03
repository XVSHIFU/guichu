import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';

const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const page=await browser.newPage({viewport:{width:1304,height:884},reducedMotion:'reduce'});
const first={id:'mock-assistant-a',name:'模拟目标 A',kind:'mcp',scope:'codex',source:'用户配置',path:'C:\\mock\\config.toml',description:'导航测试'};
const second={...first,id:'mock-assistant-b',name:'模拟目标 B'};
const sessions=[{id:'session-a',title:'A 分析',target:first,mode:'readonly',draft:'',messages:[{id:'answer-a',role:'assistant',mode:'readonly',text:'这是 A 的只读建议。'}],plan:null,accepted:false},{id:'session-b',title:'B 分析',target:second,mode:'readonly',draft:'',messages:[],plan:null,accepted:false}];
const writes=[],errors=[];let missing=false;
page.on('pageerror',error=>errors.push(error.message));
await page.addInitScript(()=>localStorage.setItem('desk-assistant-session','session-a'));
await page.route('**/api/**',async route=>{
 const request=route.request(),path=new URL(request.url()).pathname;
 if(request.method()!=='POST'){
  if(path==='/api/state'){const response=await route.fetch(),state=await response.json();state.data.objects.push(...(missing?[second]:[first,second]));return route.fulfill({json:state})}
  return route.continue();
 }
 const body=request.postDataJSON();writes.push({path,body});let result;
 if(path==='/api/model/settings')result={config:{endpoint:'https://mock.invalid',model:'mock-model'}};
 else if(path==='/api/assistant/list')result={sessions};
 else if(path==='/api/assistant/actions')result={actions:[]};
 else if(path==='/api/assistant/get')result={session:sessions.find(item=>item.id===body.id)};
 else if(path==='/api/assistant/create'){const target=[first,second].find(item=>item.id===body.target_id)||null;const session={id:'created-'+sessions.length,title:target?.name||'新对话',target,mode:'readonly',draft:'',messages:[],plan:null,accepted:false};sessions.push(session);result={session};}
 else if(path==='/api/action/list'||path==='/api/mcp-action/list')result={actions:[]};
 else return route.fulfill({status:400,json:{error:'Unexpected mocked write '+path}});
 return route.fulfill({json:result});
});
async function askFromObject(){await page.keyboard.press('Control+k');await page.getByRole('textbox',{name:'搜索所有对象',exact:true}).fill(first.name);await page.locator('.command-results button').filter({hasText:first.name}).click();await page.getByRole('button',{name:'让助手帮我处理',exact:true}).click()}
try{
 await page.goto('http://127.0.0.1:8765');await page.getByRole('button',{name:'归处助手',exact:true}).click();
 await expect(page.locator('.assistant-boundary')).toContainText('前往对象操作页核对范围并确认执行');
 await page.getByRole('button',{name:'预览并确认对象操作',exact:true}).click();
 await expect(page.getByRole('dialog')).toContainText(first.name);
 await expect(page.locator('.detail-tabs button.active')).toHaveText('操作');
 await expect(page.getByRole('button',{name:'生成配置提案',exact:true})).toBeVisible();
 assert(!writes.some(item=>/\/(propose|confirm)$/.test(item.path)));
 await page.getByRole('button',{name:'关闭详情',exact:true}).click();
 await expect(page.getByText('这是 A 的只读建议。',{exact:true})).toBeVisible();
 await askFromObject(); // Establish A as the consumed external entry.
 await page.getByRole('button',{name:/历史对话/}).click();
 await page.locator('.assistant-history-open').filter({hasText:'B 分析'}).click();
 await expect(page.locator('.composer-context')).toContainText(second.name);
 await askFromObject(); // Same object A must override the currently open B session.
 await expect(page.locator('.composer-context')).toContainText(first.name);
 await expect(page.locator('.composer-context')).not.toContainText(second.name);
 missing=true;await page.reload();await page.getByRole('button',{name:'归处助手',exact:true}).click();
 await expect(page.getByText('此对象已不在当前清单中。保留历史快照，请在变化记录中核对操作结果。',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'预览并确认对象操作',exact:true})).toBeDisabled();
 assert.deepEqual(errors,[]);
 console.log('PASS mocked assistant → exact object actions tab without proposing/confirming, return preserves chat, same-object reentry from another session, stale target guard');
}finally{await browser.close()}
