import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';
const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1435,height:1000},reducedMotion:'reduce'}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/model/settings',r=>r.fulfill({json:{config:{endpoint:'',model:''},key_configured:false}}));
 await page.goto('http://127.0.0.1:8765');const guide=page.getByRole('region',{name:'开始使用归处'});await expect(guide).toBeVisible();await expect(guide.getByText(/已收录/)).toBeVisible();
 await page.screenshot({path:'test-results/onboarding-desktop.png',fullPage:true});
 await guide.getByRole('button',{name:'配置模型'}).click();await expect(page.getByRole('tab',{name:'模型连接'})).toHaveAttribute('aria-selected','true');
 await page.getByRole('button',{name:'工作台',exact:true}).click();await guide.getByRole('button',{name:'我先自己看看'}).click();await page.reload();await expect(guide).toHaveCount(0);
 await page.getByRole('button',{name:'设置',exact:true}).click();await page.getByRole('tab',{name:'本地数据'}).click();await page.getByRole('button',{name:'打开使用引导'}).click();await expect(guide).toBeVisible();
 await page.setViewportSize({width:390,height:844});await page.reload();await expect(guide).toBeVisible();await page.screenshot({path:'test-results/onboarding-mobile.png',fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 assert.deepEqual(errors,[]);console.log('PASS first-run guide, real scan state, settings navigation, dismissal persistence, reopen and mobile bounds; no model calls');
}finally{await browser.close()}
