import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';

// Every POST is mocked. No real directory is registered, removed, or scanned.
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const page=await browser.newPage({viewport:{width:1304,height:884},reducedMotion:'reduce'});
const sources=[],writes=[],errors=[];
let offline=false;
page.on('pageerror',error=>errors.push(error.message));
await page.route('**/api/**',async route=>{
 const request=route.request(),path=new URL(request.url()).pathname;
 if(request.method()!=='POST')return offline&&path==='/api/state'?route.abort():route.continue();
 const body=request.postDataJSON();writes.push({path,body});let result;
 if(path==='/api/assistant/list')result={sessions:[]};
 else if(path==='/api/model/settings')result={config:{endpoint:'',model:'',max_output_tokens:1024,timeout:60,max_requests:3,max_tool_calls:4},key_configured:false};
 else if(path==='/api/source/list')result={sources};
 else if(path==='/api/source/add'){
  if(sources.some(source=>source.path===body.path))return route.fulfill({status:409,json:{error:'此来源已登记'}});
  const source={id:'mock-source-'+sources.length,...body};sources.push(source);result={source};
 }else if(path==='/api/source/remove'){const index=sources.findIndex(source=>source.id===body.id);assert(index>=0);sources.splice(index,1);result={ok:true};}
 else if(path==='/api/scan')result={ok:true};
 else return route.fulfill({status:400,json:{error:'Unexpected mocked write '+path}});
 return route.fulfill({json:result});
});
try{
 await page.goto('http://127.0.0.1:8765');await page.getByRole('button',{name:'设置',exact:true}).click();await page.getByRole('tab',{name:'检查来源'}).click();
 const panel=page.getByRole('region',{name:'补充检查来源'});
 await expect(panel.getByRole('button',{name:'便携软件',exact:true})).toHaveAttribute('aria-pressed','true');
 await panel.getByLabel('绝对目录路径',{exact:true}).fill('relative/path');
 await panel.getByRole('button',{name:'登记来源',exact:true}).click();
 await expect(panel.getByRole('alert')).toContainText('绝对目录路径');
 assert.equal(writes.filter(item=>item.path==='/api/source/add').length,0);
 await panel.getByLabel('绝对目录路径',{exact:true}).fill('C:\\MockPortable');
 await panel.getByLabel('显示名称（可选）',{exact:true}).fill('模拟便携工具');
 await panel.getByRole('button',{name:'登记来源',exact:true}).click();
 await expect(panel.getByText('来源登记已保存，重新检查后生效。',{exact:true})).toBeVisible();
 await expect(panel.locator('.source-list')).toContainText('模拟便携工具');
 assert.equal(writes.filter(item=>item.path==='/api/scan').length,0);
 await panel.getByRole('button',{name:'项目配置',exact:true}).click();
 await expect(panel).toContainText('.codex/config.toml 和 .mcp.json');
 await panel.getByLabel('绝对目录路径',{exact:true}).fill('D:\\MockProject');
 await panel.getByRole('button',{name:'登记来源',exact:true}).click();
 await expect(panel.locator('.source-list')).toContainText('D:\\MockProject');
 await panel.getByLabel('绝对目录路径',{exact:true}).fill('D:\\MockProject');
 await panel.getByRole('button',{name:'登记来源',exact:true}).click();
 await expect(panel.getByRole('alert')).toContainText('此来源已登记');
 await expect(panel.getByLabel('绝对目录路径',{exact:true})).toHaveValue('D:\\MockProject');
 await panel.getByRole('button',{name:'移除登记 模拟便携工具',exact:true}).click();
 await expect(panel).toContainText('只移除此来源的登记，不删除目录或文件');
 await page.screenshot({path:'test-results/source-settings.png',fullPage:true});
 await panel.getByRole('button',{name:'确认移除登记',exact:true}).click();
 await expect(panel.locator('.source-list')).not.toContainText('模拟便携工具');
 assert.equal(writes.filter(item=>item.path==='/api/scan').length,0);
 await panel.getByRole('button',{name:'重新检查',exact:true}).click();
 assert.equal(writes.filter(item=>item.path==='/api/scan').length,1);
 offline=true;
 await expect(panel.getByText('本地服务离线，暂不可新增或移除来源登记。',{exact:true})).toBeVisible({timeout:10000});
 await expect(panel.getByRole('button',{name:'登记来源',exact:true})).toBeDisabled();
 assert.deepEqual(errors,[]);
 console.log('PASS mocked source type/path validation/add/duplicate/remove-only/explicit scan/offline; no real registration or file changes');
}finally{await browser.close()}
