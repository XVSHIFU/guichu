import React,{useState} from 'react';
export const channels=['未知','Microsoft Store','winget','Scoop','Chocolatey','npm','pnpm','Yarn','pip','pipx','uv','Conda','手动安装','系统预装','其他'];
const fields=[['channel','安装渠道',channels],['method','安装方式',['未知','安装包','MSI','MSIX / AppX','便携版','包管理器','源码构建']],['download','下载来源',['未知','Microsoft Store','GitHub Releases','软件官网','包仓库','其他网站','本地 / 离线文件']]];
export const channelLabel=o=>o.softwareOrigin?.channel||'未知';
export default function SoftwareOrigin({obj,post,load,disabled,Select}){
 const [editing,setEditing]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const origin=obj.softwareOrigin||{},[draft,setDraft]=useState({});
 if(!['software','agent'].includes(obj.kind))return null;
 async function save(){setBusy(true);setError('');try{await post('software-origin',{id:obj.id,value:draft});await load();setEditing(false)}catch(e){setError(e.message)}finally{setBusy(false)}}
 return <section className="detail-section"><h3>安装来源</h3>{editing?<><div className="origin-edit">{fields.map(([key,label,options])=><label key={key}>{label}<Select label={label} value={draft[key]||'自动识别'} options={['自动识别',...options]} disabled={busy||disabled} onChange={value=>setDraft(previous=>{const next={...previous};if(value==='自动识别')delete next[key];else next[key]=value;return next})}/></label>)}</div><button className="button" disabled={busy||disabled} onClick={save}>保存来源</button> <button className="text-button" disabled={busy} onClick={()=>setEditing(false)}>取消</button></>:<><dl>{fields.map(([key,label])=><div key={key}><dt>{label}</dt><dd>{origin[key]||'未知'}{origin.manualFields?.includes(key)&&<small> · 手动标记</small>}</dd></div>)}</dl><button className="text-button" disabled={disabled} onClick={()=>{setDraft(Object.fromEntries((origin.manualFields||[]).map(key=>[key,origin[key]])));setEditing(true)}}>补充或修改来源</button>{origin.evidence?.length>0&&<details className="origin-evidence"><summary>查看依据</summary>{origin.evidence.map(text=><p key={text}>{text}</p>)}</details>}</>}{error&&<p role="alert">{error}</p>}</section>;
}
