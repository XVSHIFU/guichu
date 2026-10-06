import {chromium, expect} from '@playwright/test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';

// Serve only built assets. Every API response is isolated; no workbench data writes.
const dist=path.resolve('dist');
const server=http.createServer(async(req,res)=>{
 try{
  const relative=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
  const file=path.resolve(dist,'.'+(relative==='/'?'/index.html':relative));
  if(!file.startsWith(dist+path.sep)){res.writeHead(403).end();return}
  const types={'.js':'text/javascript','.css':'text/css','.html':'text/html','.svg':'image/svg+xml','.woff2':'font/woff2'};
  res.setHeader('Content-Type',types[path.extname(file)]||'application/octet-stream');res.end(await fs.readFile(file));
 }catch{res.writeHead(404).end()}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1304,height:900},reducedMotion:'reduce'}),errors=[],writes=[];
 page.on('pageerror',e=>{errors.push(e.message);console.error(e.stack)});
 await page.addInitScript(()=>localStorage.setItem('desk-onboarding','hidden'));
 const base={checkedAt:'2026-10-03T10:00:00+08:00',source:'隔离扫描样本',description:'用于核对扫描证据的样本。'};
 const objects=[{...base,id:'a',name:'Sample Agent',kind:'agent',status:'运行中',processCount:2,commandFound:true},
  {...base,id:'m',name:'Sample MCP',kind:'mcp',status:'配置启用',transport:'stdio',enabled:true},
  {...base,id:'s',name:'Unknown Skill',kind:'skill',status:'已发现',enabled:null}];
 await page.route('**/api/**',async route=>{
  const name=new URL(route.request().url()).pathname;
  if(route.request().method()==='POST')writes.push(name);
  const json=name==='/api/state'?{token:'fixture',scan:{running:false},scan_history:[],data:{objects,relations:[],notes:{},changes:[],issues:[],disks:[],at:base.checkedAt,machine:'Sample',scope:'隔离范围'}}:
   name==='/api/model/catalog'?{providers:[],active_id:null}:name==='/api/agent/preferences'?{preferences:{instructions:''}}:
   name==='/api/mcp-client/list'?{servers:[]}:name==='/api/assistant/list'?{sessions:[]}:
   name==='/api/vitals'?{cpu:0,memory:0}:name==='/api/source/list'?{sources:[]}:name==='/api/model/settings'?{config:{},key_configured:false}:{};
  await route.fulfill({json});
 });
 await page.goto(`http://127.0.0.1:${server.address().port}`);
 await page.locator('.agent-row').first().click();
 await expect(page.locator('.object-preview')).toContainText('扫描时间');
 await expect(page.locator('.object-preview')).toContainText('扫描时有同名进程');
 await expect(page.locator('.object-drawer')).toHaveCount(0);
 await page.locator('.object-preview').click();
 await expect(page.locator('.object-drawer')).toContainText('2 个（身份未验证）');
 await expect(page.locator('.object-drawer')).toContainText('当前运行情况尚未验证');
 await page.screenshot({path:'test-results/evidence-desktop.png',fullPage:true});
 await page.keyboard.press('Escape');
 await page.getByRole('button',{name:'技能与连接',exact:true}).click();
 await page.locator('.object-row').filter({hasText:'Sample MCP'}).click();
 await page.locator('.object-preview').click();
 await expect(page.locator('.object-drawer')).toContainText('未提供');
 await expect(page.locator('.object-drawer')).toContainText('未测试');
 await page.setViewportSize({width:390,height:844});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.screenshot({path:'test-results/evidence-mobile.png',fullPage:true});
 await page.keyboard.press('Escape');
 await page.setViewportSize({width:1304,height:900});
 await page.locator('.object-row').filter({hasText:'Unknown Skill'}).click();
 await page.locator('.object-preview').click();
 await expect(page.locator('.object-drawer')).toContainText('启用状态未知');
 await expect(page.locator('.object-drawer')).not.toContainText('配置已停用');
 await page.keyboard.press('Escape');
 await page.getByRole('button',{name:'设置',exact:true}).click();
 await page.getByRole('tab',{name:'检查来源'}).click();
 await page.getByLabel('绝对目录路径',{exact:true}).fill('\\\\server\\share');
 await page.getByRole('button',{name:'登记来源',exact:true}).click();
 await expect(page.getByRole('alert')).toContainText('不支持网络共享');
 assert(!writes.includes('/api/source/add'));
 assert.deepEqual(errors,[]);
 console.log('PASS isolated evidence labels, selection before details, mobile layout, UNC rejection');
}finally{await browser.close();await new Promise(resolve=>server.close(resolve))}
