import {chromium,expect} from '@playwright/test';
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
try{
const page=await browser.newPage({viewport:{width:990,height:884}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto('http://127.0.0.1:8765');await page.getByRole('button',{name:'设置',exact:true}).click();
await page.getByRole('button',{name:'编辑',exact:true}).first().click();await expect(page.getByLabel('提供商名称',{exact:true})).toBeEnabled();await page.getByLabel('提供商名称',{exact:true}).fill('unsaved-draft');
await page.getByRole('tab',{name:'检查来源'}).click();await expect(page.getByRole('heading',{name:'补充检查来源'})).toBeVisible();await expect(page.getByLabel('提供商名称',{exact:true})).toBeHidden();
await page.getByRole('tab',{name:'模型连接'}).click();await expect(page.getByLabel('提供商名称',{exact:true})).toHaveValue('unsaved-draft');
await page.getByRole('tab',{name:'模型连接'}).focus();await page.keyboard.press('ArrowDown');await expect(page.getByRole('tab',{name:'检查来源'})).toBeFocused();await page.keyboard.press('Home');
await page.screenshot({path:'test-results/settings-categories-desktop.png'});
await page.getByRole('tab',{name:'外观'}).click();await expect(page.getByRole('group',{name:'明暗模式'})).toBeVisible();
await page.setViewportSize({width:390,height:844});await page.getByRole('tab',{name:'模型连接'}).click();await page.screenshot({path:'test-results/settings-categories-mobile.png'});
if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('horizontal overflow');if(errors.length)throw Error(errors.join());console.log('PASS category navigation, keyboard, unsaved draft retained, mobile overflow; no settings saved');
}finally{await browser.close()}
