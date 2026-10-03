import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1435,height:884}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let proposal={id:'p1',revision:1,family:'category-action',state:'pending',object:{id:'a',name:'2 个软件'},preview:{targets:[{id:'a',name:'Alpha'},{id:'b',name:'Beta'}],before:{a:null,b:['其他软件','old']},after:{a:['开发工具',null],b:['办公与协作',null]}}};
 const session=()=>({id:'s1',title:'整理清单',mode:'readonly',draft:'',target:null,messages:[{id:'a1',role:'assistant',mode:'readonly',text:'请确认变更。',proposals:[proposal]}]});
 await page.addInitScript(()=>localStorage.setItem('desk-assistant-session','s1'));
 await page.route('**/api/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname;if(req.method()!=='POST')return route.continue();
  const result=path.endsWith('/model/settings')?{config:{model:'mock'}}:path.endsWith('/assistant/list')?{sessions:[session()]}:path.endsWith('/assistant/get')?{session:session()}:path.endsWith('/assistant/actions')?{actions:[]}:null;
  if(result)return route.fulfill({json:result});return route.fulfill({status:400,json:{error:'unexpected '+path}});
 });
 async function open(){await page.goto('http://127.0.0.1:8765');await page.getByRole('button',{name:'归处助手',exact:true}).click()}
 await open();const card=page.locator('.agent-proposal');await expect(card).toContainText('批量调整软件分类');await expect(card).toContainText('自动分类 → 开发工具');await expect(card).toContainText('其他软件 → 办公与协作');
 await page.screenshot({path:'test-results/agent-batch-proposal.png'});
 proposal.operation='restore';await open();await expect(card).toContainText('开发工具 → 自动分类');await expect(card).toContainText('办公与协作 → 其他软件');
 proposal={id:'p2',revision:1,family:'claude-action',state:'pending',object:{id:'c',name:'检索工具'},preview:{path:'C:/mock/.claude.json',before_enabled:true,after_enabled:false}};
 await open();await expect(card).toContainText('移除 Claude MCP 注册');await expect(card).toContainText('不会卸载服务');await expect(card).toContainText('已注册');
 await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(errors,[]);
 console.log('PASS batch differences/restoration, explicit Claude removal wording, mobile bounds; no configuration writes');
}finally{await browser.close()}
