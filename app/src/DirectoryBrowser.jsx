import React,{useState,useRef} from 'react';
import {HardDrive,Folder,File,ChevronRight,ArrowLeft,RefreshCw,Search,Copy,Info,LoaderCircle} from 'lucide-react';
import DirectorySize from './DirectorySize';

export default function DirectoryBrowser({disks,objects,post,offline,select,copy}){
 const [path,setPath]=useState(''),[listing,setListing]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[query,setQuery]=useState(''),[mode,setMode]=useState('全部');const request=useRef(0);
 const [analysis,setAnalysis]=useState(false);
 const known=objects.filter(o=>o.kind==='directory');
 async function open(target,q='',m='全部',cursor=null){
  const id=++request.current;
  const sameDirectory=target===path;
  setPath(target);setQuery(q);setMode(m);setBusy(true);setError('');
  if(!sameDirectory)setListing(null);
  try{
   const result=await post('browse',{path:target,query:q,mode:m,...(cursor?{cursor}:{})});
   if(id===request.current)setListing(previous=>({...result,query:q,mode:m,entries:cursor&&previous?[...previous.entries,...result.entries]:result.entries}));
  }catch(e){if(id===request.current)setError(e.message)}
  finally{if(id===request.current)setBusy(false)}
 }
 function home(){request.current++;setPath('');setListing(null);setError('');setBusy(false);setQuery('')}
 const parent=listing?.parent||(path.replace(/[\\/]+$/,'').split(/[/\\]/).length>1?path.replace(/[\\/][^\\/]+[\\/]?$/,'')+'\\':null);
 return <div className="directory-browser"><div className="directory-crumb"><button onClick={home}>全部磁盘</button>{path&&<><ChevronRight size={14}/><code>{path}</code><button className="icon-button" aria-label="复制当前目录" onClick={()=>copy(path)}><Copy size={15}/></button></>}</div>
 {!path?<><div className="section-title"><h2>本机磁盘</h2><span>选择磁盘开始浏览</span></div><div className="drive-list">{disks.map(d=><button key={d.path} onClick={()=>open(d.path)} disabled={offline} className="drive-row"><HardDrive size={23}/><div><strong>{d.path}</strong><div className="disk-track"><span style={{width:d.percent+'%'}}/></div><small>{(d.free/2**30).toFixed(1)} GiB 可用 / {(d.total/2**30).toFixed(1)} GiB</small></div><ChevronRight size={17}/></button>)}</div></>:<>
 {!analysis&&<><div className="directory-toolbar"><button className="button" onClick={()=>parent?open(parent):home()} disabled={busy}><ArrowLeft size={14}/>上一级</button><button className="icon-button" aria-label="刷新当前目录" disabled={busy||offline} onClick={()=>open(path,query,mode)}><RefreshCw size={15}/></button><form onSubmit={e=>{e.preventDefault();if(!offline)open(path,query,mode)}} className="inline-search"><Search size={15}/><input aria-label="筛选当前目录" placeholder="搜索当前层，回车确认" value={query} onChange={e=>setQuery(e.target.value)}/></form></div><div className="filter-tabs">{['全部','文件夹','文件'].map(m=><button key={m} className={mode===m?'active':''} disabled={busy||offline} onClick={()=>open(path,query,m)}>{m}</button>)}</div>
 </>}
 <DirectorySize path={path} post={post} offline={offline} onBrowse={p=>open(p)} onAnalysisChange={setAnalysis}/>
 {!analysis&&<>
 {listing&&<div className="list-caption"><span>{listing.directoryCount} 个文件夹 · {listing.fileCount} 个文件</span><span>显示 {listing.entries.length} / {listing.total} 项</span></div>}
 {error&&<div className="error-banner" role="alert"><span>{error}{listing?' · 当前显示上次读取的结果，可能已过期。':''}</span><button disabled={offline||busy} onClick={()=>open(path,query,mode)}>重新读取</button></div>}
 {listing?.entries.map(e=>{const obj=known.find(o=>o.path.toLowerCase()===e.path.toLowerCase());return <div className="folder-row" key={e.path}><button className="folder-main" disabled={!e.directory||e.link||offline} onClick={()=>open(e.path)}>{e.directory?<Folder size={18}/>:<File size={18}/>}<span><strong>{e.name}</strong><small>{e.link?'链接目录 · 不自动跟随':e.directory?'文件夹': '文件 · 仅展示名称'}</small></span>{e.directory&&!e.link&&<ChevronRight size={15}/>}</button>{obj?<button className="icon-button" aria-label={'查看 '+e.name+' 详情'} onClick={()=>select(obj.id)}><Info size={16}/></button>:<button className="icon-button" aria-label={'复制 '+e.name+' 路径'} onClick={()=>copy(e.path)}><Copy size={15}/></button>}</div>})}
 {busy&&<div className="directory-loading" role="status"><LoaderCircle className="spin" size={17}/>{listing?'正在更新，暂时显示上次结果…':'正在读取当前目录…'}</div>}
 {!busy&&listing?.total===0&&<div className="empty-state"><Folder/><h2>{listing.query?'没有匹配项目':'当前分类没有项目'}</h2><p>可切换分类或返回上一级。</p></div>}
 {listing?.next!=null&&!busy&&!error&&<button className="button" onClick={()=>open(path,listing.query,listing.mode,listing.next)}>加载更多</button>}
 </>}
 </>}
</div>
}
