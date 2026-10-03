export async function toggleAppearance(page){
 await page.getByRole('button',{name:'选择主题',exact:true}).first().click();
 const next=await page.locator('html').getAttribute('data-theme')==='dark'?'浅色':'深色';
 await page.getByRole('dialog',{name:'外观主题',exact:true}).getByRole('button',{name:next,exact:true}).click();
 await page.keyboard.press('Escape');
}
