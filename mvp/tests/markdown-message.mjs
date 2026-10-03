import {createServer} from 'vite';
import {chromium, expect} from '@playwright/test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const server = await createServer({server:{host:'127.0.0.1',port:0},appType:'custom'});
server.middlewares.use('/markdown-test', async (_req,res) => {
  res.setHeader('Content-Type','text/html');
  res.end(await server.transformIndexHtml('/markdown-test',`<html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><main id="root" style="max-width:680px;margin:20px auto"></main><script type="module">
import React from 'react';
import {createRoot} from 'react-dom/client';
import MarkdownMessage from '/src/MarkdownMessage.jsx';
import '/src/style.css';
const root=createRoot(document.getElementById('root'));
window.renderMarkdown=text=>root.render(React.createElement(MarkdownMessage,{text}));
window.renderMarkdown('Ready');
</script></body></html>`));
});
await server.listen();
const browser = await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
try {
  const page = await browser.newPage();
  const errors=[]; const remote=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.url().includes('untrusted.example'))remote.push(r.url());});
  await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/markdown-test`);
  await page.waitForFunction(()=>typeof window.renderMarkdown==='function');
  await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copied=text;}},configurable:true}));
  const source=['# 检查结果','','**重点** 与 `inline`','','- 第一项','- 第二项','','> 引用说明','','| 名称 | 状态 |','| --- | --- |','| 工作目录 | 可读取 |','','```python','print("hello")', 'x'.repeat(250),'```','','[官网](https://example.com)','[恶意](javascript:alert%281%29)','[数据](data:text/html,test)','![说明](https://untrusted.example/tracker.png)','','<script>window.executed=true</script>','','<img src="https://untrusted.example/raw" onerror="window.executed=true">'].join('\n');
  await page.evaluate(text=>window.renderMarkdown(text),source);
  await expect(page.locator('.markdown-message h1')).toHaveText('检查结果');
  await expect(page.locator('.markdown-message strong')).toHaveText('重点');
  await expect(page.locator('table tbody tr')).toHaveCount(1);
  await expect(page.locator('blockquote')).toContainText('引用说明');
  await expect(page.locator('.markdown-message li')).toHaveCount(2);
  await expect(page.locator('.markdown-message img,.markdown-message script')).toHaveCount(0);
  await expect(page.locator('.markdown-message a')).toHaveCount(1);
  await expect(page.locator('.markdown-message a')).toHaveAttribute('rel','noopener noreferrer');
  await page.getByRole('button',{name:'复制代码'}).click();
  await expect(page.getByRole('status')).toHaveText('已复制');
  assert.equal(await page.evaluate(()=>window.copied),`print("hello")\n${'x'.repeat(250)}\n`);
  assert.equal(await page.evaluate(()=>window.executed),undefined);
  assert.deepEqual(remote,[]);
  fs.mkdirSync('test-results',{recursive:true});
  await page.screenshot({path:'test-results/markdown-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.evaluate(()=>document.documentElement.dataset.theme='dark');
  await page.screenshot({path:'test-results/markdown-mobile-dark.png',fullPage:true});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  assert.equal(await page.locator('pre').evaluate(el=>el.scrollWidth>el.clientWidth),true);
  await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{value:{writeText:async()=>{throw Error('denied');}},configurable:true}));
  await page.getByRole('button',{name:'复制代码'}).click();
  await expect(page.getByRole('status')).toContainText('复制失败');
  for(const text of ['```js\nconst a =','**未完成','[链接](','| 表格 |\n| --- |\n| 内容','']) {
    await page.evaluate(value=>window.renderMarkdown(value),text);
    await page.waitForTimeout(30);
  }
  assert.deepEqual(errors,[]);
  console.log('Markdown browser checks passed: GFM, clipboard success/failure, blocked HTML/URLs/images, mobile overflow, incomplete streaming.');
} finally {await browser.close();await server.close();}
