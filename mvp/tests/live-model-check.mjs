import {chromium,expect} from '@playwright/test';
import fs from 'node:fs';
const evidence=JSON.parse(fs.readFileSync('test-results/live-model-run.json','utf8'));
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1304,height:884}});
 await page.addInitScript(id=>localStorage.setItem('desk-assistant-session',id),evidence.session_id);
 await page.goto('http://127.0.0.1:8765');
 await page.locator('.nav-item').filter({hasText:'归处助手'}).click();
 await expect(page.locator('.assistant-run').getByText('分析完成',{exact:true})).toBeVisible();
 await expect(page.locator('.assistant-run')).toContainText('get_object');
 await expect(page.locator('.assistant-run')).toContainText('4068');
 await page.screenshot({path:'test-results/live-model-history.png',fullPage:true});
 console.log('PASS real model history rendered with successful tool and usage');
}finally{await browser.close()}
