import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1435,height:1000},reducedMotion:'reduce'}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/**',async route=>route.request().method()==='POST'?route.fulfill({json:{providers:[],active_id:null,sources:[],sessions:[],servers:[],preferences:{instructions:''}}}):route.continue());
 await page.goto('http://127.0.0.1:8765');await page.getByRole('button',{name:'设置',exact:true}).click();await page.getByRole('tab',{name:'外观'}).click();
 const library=page.getByRole('region',{name:'主题配色集'}),names=await page.evaluate(()=>DeskThemes.themes.map(t=>({id:t.id,name:t.name})));
 assert.equal(names.length,28);
 for(const group of ['自然','纸与火','花与金属','城市与夜','社区']){
  await page.getByRole('button',{name:group,exact:true}).click();await expect(library.locator('.theme-sample')).toHaveCount(group==='社区'?4:6);
  const labels=await library.locator('.theme-sample').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('aria-label')));
  for(const label of labels){await page.getByRole('button',{name:label,exact:true}).click();await expect(page.getByRole('button',{name:label,exact:true})).toHaveAttribute('aria-pressed','true');}
 }
 await page.getByRole('button',{name:'选择主题',exact:true}).first().click();const wheel=page.getByRole('dialog',{name:'外观主题',exact:true});await wheel.focus();
 for(let i=0;i<29;i++){await page.keyboard.press('ArrowRight');await expect(wheel.locator('.theme-wheel-swatch:visible')).toHaveCount(3);}
 await page.keyboard.press('Escape');
 for(const [mode,group,width] of [['light','社区',1435],['dark','社区',1435],['light','社区',390],['dark','社区',390]]){
  await page.setViewportSize({width,height:width===390?844:1000});await page.locator('.appearance-settings').getByRole('button',{name:mode==='light'?'浅色':'深色',exact:true}).click();await page.getByRole('button',{name:group,exact:true}).click();await library.locator('.theme-sample').last().click();await library.scrollIntoViewIfNeeded();await page.screenshot({path:`test-results/theme-library-${mode}-${width}.png`,fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 }
 const saved=await page.evaluate(()=>document.documentElement.dataset.palette);await page.reload();await expect(page.locator('html')).toHaveAttribute('data-palette',saved);assert.deepEqual(errors,[]);console.log('PASS all 28 gallery choices, 29 wheel steps with no overlap, light/dark desktop/mobile, saved first paint');
}finally{await browser.close()}
