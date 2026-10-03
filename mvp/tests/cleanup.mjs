import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';

// Synthetic objects and mocked POSTs: never recycle, uninstall, or open OS windows.
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
const page=await browser.newPage({viewport:{width:1304,height:884},reducedMotion:'reduce'});
const directory={id:'mock-recycle',kind:'directory',name:'模拟回收目录',path:'C:\\MockRecycle',source:'测试',description:'仅用于mock测试'};
const software={id:'mock-msi',kind:'software',name:'模拟 MSI 软件',path:'C:\\MockSoftware',source:'本机级注册表',scope:'本机',description:'仅用于mock测试'};
const actions=[],writes=[],errors=[];
let recycled=false,removed=false,unsupported=true,verifyCount=0;
page.on('pageerror',error=>errors.push(error.message));
await page.route('**/api/**',async route=>{
 const request=route.request(),path=new URL(request.url()).pathname;
 if(request.method()!=='POST'){
  if(path==='/api/state'){const response=await route.fetch(),state=await response.json();state.data.objects.push(...[recycled?null:directory,removed?null:software].filter(Boolean));return route.fulfill({json:state})}
  return route.continue();
 }
 const body=request.postDataJSON();writes.push({path,body});let result;
 if(path==='/api/assistant/list')result={sessions:[]};
 else if(path==='/api/action/list')result={actions:[]};
 else if(path==='/api/cleanup/list')result={actions};
 else if(path==='/api/cleanup/open-bin')result={ok:true};
 else if(path==='/api/cleanup/propose'){
  assert.match(body.request_id,/^[\da-f-]{36}$/i);
  if(body.kind==='uninstall'&&unsupported)return route.fulfill({status:400,json:{error:'当前软件暂不支持可核验的 Windows MSI 卸载'}});
  const object=body.kind==='recycle'?directory:software;
  const preview=body.kind==='recycle'?{path:object.path,files:3,directories:2,bytes:4096,processes:[],usage_check:'partial'}:{name:object.name,product_code:'{00000000-0000-0000-0000-000000000001}',installer_path:'C:\\Windows\\System32\\msiexec.exe',version:'1.0'};
  const action={id:'mock-cleanup-'+actions.length,revision:1,object:{...object},path:object.path,kind:body.kind,state:'pending',preview};actions.unshift(action);result={action};
 }else if(path==='/api/cleanup/confirm'){
  const action=actions.find(item=>item.id===body.id);assert(action);assert.equal(body.acknowledge,true);assert.equal(body.revision,1);
  action.state=action.kind==='recycle'?'recycled':'waiting_user';if(action.kind==='recycle')recycled=true;result={action};
 }else if(path==='/api/cleanup/verify'){
  const action=actions.find(item=>item.id===body.id);assert(action);verifyCount++;action.state=verifyCount===1?'still_registered':'removed';if(action.state==='removed')removed=true;result={action};
 }else return route.fulfill({status:400,json:{error:'Unexpected mocked write '+path}});
 return route.fulfill({json:result});
});
async function openObject(name){await page.keyboard.press('Control+k');await page.getByRole('textbox',{name:'搜索所有对象',exact:true}).fill(name);await page.locator('.command-results button').filter({hasText:name}).click();await page.locator('.object-preview').click();await page.getByRole('button',{name:'操作',exact:true}).click()}
try{
 await page.goto('http://127.0.0.1:8765');await openObject(directory.name);
 let panel=page.getByRole('region',{name:'目录回收',exact:true});
 await panel.getByRole('button',{name:'预览回收范围',exact:true}).click();
 await expect(panel).toContainText(directory.path);await expect(panel).toContainText('4,096 字节');await expect(panel).toContainText('部分进程信息无法读取');
 await expect(panel.getByRole('button',{name:'确认移到回收站',exact:true})).toBeDisabled();
 assert.equal(writes.filter(item=>item.path==='/api/cleanup/confirm').length,0);
 await panel.screenshot({path:'test-results/cleanup-recycle-preview.png'});
 await panel.getByRole('checkbox').check();await panel.getByRole('button',{name:'确认移到回收站',exact:true}).click();
 await expect(page.getByRole('dialog')).toHaveCount(0);
 await page.getByRole('button',{name:'变化记录',exact:true}).click();
 const history=page.getByRole('region',{name:'清理操作记录',exact:true});
 await history.getByText('查看全部清理操作',{exact:true}).click();
 await history.getByRole('button',{name:/模拟回收目录 · 目录回收/}).click();
 await expect(history).toContainText(directory.path);
 await history.getByRole('button',{name:'打开回收站',exact:true}).click();
 await expect.poll(()=>writes.filter(item=>item.path==='/api/cleanup/open-bin').length).toBe(1);
 actions[0].state='interrupted';actions[0].receipt={state:'uncertain'};
 await history.getByRole('button',{name:'刷新清理记录',exact:true}).click();
 await expect(history).toContainText('执行结果可能不确定');await expect(history.getByRole('button',{name:'打开回收站',exact:true})).toBeVisible();
 await history.screenshot({path:'test-results/cleanup-history-interrupted.png'});
 await openObject(software.name);panel=page.getByRole('region',{name:'官方软件卸载',exact:true});
 await panel.getByRole('button',{name:'预览官方卸载',exact:true}).click();
 await expect(panel.getByRole('alert')).toContainText('暂不支持');unsupported=false;
 await panel.getByRole('button',{name:'预览官方卸载',exact:true}).click();
 await expect(panel.getByRole('button',{name:'打开官方卸载程序',exact:true})).toBeDisabled();
 await panel.getByRole('checkbox').check();await panel.getByRole('button',{name:'打开官方卸载程序',exact:true}).click();
 await expect(panel.locator('.cleanup-preview-heading')).toContainText('等待你完成官方卸载');
 await panel.screenshot({path:'test-results/cleanup-msi-waiting.png'});
 await panel.getByRole('button',{name:'重新核对注册状态',exact:true}).click();
 await expect(panel.locator('.cleanup-preview-heading')).toContainText('仍有卸载注册记录');
 await panel.getByRole('button',{name:'重新核对注册状态',exact:true}).click();
 await expect(page.getByRole('dialog')).toHaveCount(0);
 await page.getByRole('button',{name:'变化记录',exact:true}).click();
 await history.getByText('查看全部清理操作',{exact:true}).click();
 await history.getByRole('button',{name:/模拟 MSI 软件 · 官方卸载/}).click();
 await expect(history.locator('.cleanup-preview-heading')).toContainText('注册状态已移除');
 assert.deepEqual(errors,[]);assert(writes.every(item=>item.path.startsWith('/api/cleanup/')||['/api/action/list','/api/assistant/list'].includes(item.path)));
 console.log('PASS mocked recycle scope/acknowledgement, vanished object history, uncertain recovery entry, unsupported MSI, interactive waiting→verify states; no real cleanup or OS launch');
}finally{await browser.close()}
