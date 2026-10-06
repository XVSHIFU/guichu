import FileRanking from './FileRanking';
import React,{useState,useRef,useEffect} from 'react';
import {Folder,File,ArrowLeft,ChevronRight} from 'lucide-react';
import './space-analysis.css';
import DirectoryFiles from './DirectoryFiles';
const size=n=>n>=2**30?(n/2**30).toFixed(2)+' GiB':n>=2**20?(n/2**20).toFixed(1)+' MiB':n>=1024?(n/1024).toFixed(1)+' KiB':n+' B';
function tiles(items,x=0,y=0,w=100,h=100){
 if(!items.length)return [];
 if(items.length===1)return [{...items[0],x,y,w,h}];
 const total=items.reduce((n,o)=>n+o.bytes,0);let sum=0,split=1;
 for(let i=0;i<items.length-1;i++){sum+=items[i].bytes;split=i+1;if(sum>=total/2)break}
 const ratio=sum/total;
 return w>=h?[...tiles(items.slice(0,split),x,y,w*ratio,h),...tiles(items.slice(split),x+w*ratio,y,w*(1-ratio),h)]:[...tiles(items.slice(0,split),x,y,w,h*ratio),...tiles(items.slice(split),x,y+h*ratio,w,h*(1-ratio))];
}
export default function SpaceAnalysis({task,onBrowse,post}){
 const [selected,setSelected]=useState(null),[sort,setSort]=useState('bytes'),[mode,setMode]=useState('tree');
 const mapRef=useRef(null),[mapSize,setMapSize]=useState({width:700,height:230});
 useEffect(()=>{const node=mapRef.current;if(!node)return;const observer=new ResizeObserver(([entry])=>setMapSize({width:entry.contentRect.width,height:entry.contentRect.height}));observer.observe(node);return()=>observer.disconnect()},[mode]);
 const [groups,setGroups]=useState([]),[hovered,setHovered]=useState(null);
 const [expanded,setExpanded]=useState(null);
 const [extra,setExtra]=useState([]),[loadingPath,setLoadingPath]=useState(''),[loadError,setLoadError]=useState(''),[subtaskId,setSubtaskId]=useState(null);
 const pending=useRef(false),alive=useRef(true);
 useEffect(()=>{alive.current=true;return()=>{alive.current=false}},[]);
 const [motion,setMotion]=useState(''),timer=useRef(null);
 useEffect(()=>()=>clearTimeout(timer.current),[]);
 function navigate(path,back=false){setGroups([]);setHovered(null);setExpanded(null);clearTimeout(timer.current);const direction=back?'out':'in';if(window.matchMedia('(prefers-reduced-motion: reduce)').matches){setSelected(path);setMotion('');return}setMotion('leave-'+direction);timer.current=setTimeout(()=>{setSelected(path);setMotion('enter-'+direction);timer.current=setTimeout(()=>setMotion(''),280)},140)}
 const tree=[...(task.tree||[]).filter(n=>!extra.some(e=>e.path===n.path)),...extra],current=tree.find(n=>n.path===selected)||tree.find(n=>n.path===task.path);
 if(!current)return null;
 const allRows=(mode==='files'?(task.largest_files||[]):tree.filter(n=>n.parent===current.path)).slice().sort((a,b)=>sort==='name'?(a.name||a.path).localeCompare(b.name||b.path,'zh-CN'):(b[sort]||0)-(a[sort]||0));
 const rows=groups.length?allRows.filter(o=>groups.at(-1).includes(o.path)):allRows;
 const total=rows.reduce((n,o)=>n+o.bytes,0),positive=rows.filter(o=>o.bytes>0).sort((a,b)=>b.bytes-a.bytes);
 const small=o=>o.w*mapSize.width/100<90||o.h*mapSize.height/100<48;
 const initial=tiles(positive);
 let grouped=initial.filter((o,i)=>small(o)||i>=39);
 if(grouped.length===positive.length)grouped=grouped.slice(1);
 const groupedPaths=new Set(grouped.map(o=>o.path));
 const others=grouped.length>1?{path:'other',name:'其他 '+grouped.length+' 项',bytes:grouped.reduce((n,o)=>n+o.bytes,0),other:true}:null;
 const map=others?tiles([...positive.filter(o=>!groupedPaths.has(o.path)),others]):initial;
 function openGroup(){setExpanded(null);setHovered(null);setGroups(previous=>[...previous,grouped.map(o=>o.path)])}
 function changeMode(next){setMode(next);setGroups([]);setHovered(null);setExpanded(null)}
 const complete=o=>o.complete??(task.status==='succeeded'&&!task.tree_truncated);
 const measured=o=>complete(o)?size(o.bytes):o.bytes?`≥ ${size(o.bytes)}`:'未统计';
 const leaf=path=>!tree.some(n=>n.parent===path);
 async function choose(path){
  if(!leaf(path)){navigate(path);return}
  if(pending.current)return;
  if(expanded===path){setExpanded(null);return}
  pending.current=true;setLoadingPath(path);setLoadError('');
  try{
   const listing=await post('browse',{path,mode:'文件夹'});
   if(!alive.current)return;
   if(!listing.directoryCount){
    if(listing.read_errors)throw Error('目录未能完整读取，暂时无法判断是否包含子目录。');
    setExpanded(path);return;
   }
   const parent=tree.find(n=>n.path===path)?.parent;
   let result=await post('size/start',{path,request_id:crypto.randomUUID(),scan_mode:task.scan_mode||'standard'});
   setSubtaskId(result.task.id);navigate(path);
   while(alive.current){
    if(result.task.tree){const nodes=result.task.tree.map(n=>n.path===path?{...n,parent}:n);setExtra(old=>[...old.filter(n=>!nodes.some(e=>e.path===n.path)),...nodes]);}
    if(!['queued','running'].includes(result.task.status)){if(result.task.error)throw Error(result.task.error);break}
    await new Promise(resolve=>setTimeout(resolve,800));
    if(!alive.current)break;
    result=await post('size/get',{id:result.task.id});
   }
  }catch(e){if(alive.current)setLoadError(e.message||'无法读取子目录，请重试。')}
  finally{pending.current=false;if(alive.current){setLoadingPath('');setSubtaskId(null)}}
 }
 return <section className="space-analysis" aria-label="空间分布"><div className="space-analysis-toolbar"><button className="text-button" disabled={mode==='files'||(!groups.length&&!current.parent)} onClick={()=>groups.length?(setGroups(g=>g.slice(0,-1)),setExpanded(null),setHovered(null)):navigate(current.parent,true)}><ArrowLeft size={14}/>上一级</button><code>{mode==='tree'?current.path:'本次扫描 · 最多 200 个文件'}{groups.length>0?' / 小项':''}</code><div className="filter-tabs"><button className={mode==='tree'?'active':''} onClick={()=>changeMode('tree')}>目录树</button><button className={mode==='files'?'active':''} onClick={()=>changeMode('files')}>文件排行</button></div></div>
 {loadingPath&&<p className="space-note" role="status">正在补充此目录的空间分布… {subtaskId&&<button className="text-button" onClick={()=>post('size/cancel',{id:subtaskId}).catch(e=>setLoadError(e.message))}>停止补充</button>}</p>}{loadError&&<p className="space-note" role="alert">{loadError}</p>}
 {mode==='files'?<FileRanking task={task} post={post}/>:<div className={"space-level "+motion} aria-busy={motion.startsWith("leave")}><div ref={mapRef} className="space-treemap" aria-label="按逻辑大小绘制的空间矩形图">{map.map((o,i)=><button key={o.path} aria-label={`${o.name} · ${size(o.bytes)}`} className={small(o)?"small-tile":""} title={`${o.name} · ${size(o.bytes)}`} disabled={mode==='files'&&!o.other} aria-expanded={leaf(o.path)?expanded===o.path:undefined} onMouseEnter={()=>setHovered(o)} onMouseLeave={()=>setHovered(null)} onFocus={()=>setHovered(o)} onBlur={()=>setHovered(null)} onClick={()=>o.other?openGroup():choose(o.path)} style={{left:o.x+'%',top:o.y+'%',width:o.w+'%',height:o.h+'%','--tile-index':i%4}}><strong>{o.name}</strong><span>{size(o.bytes)}</span></button>)}{!map.length&&<p className="space-map-empty">{task.tree_truncated?"此层未记录可展示的子目录，统计可能达到展示上限。":"此目录没有有大小的子目录。可切换“文件排行”查看。"}</p>}</div>
 <div className="space-map-caption"><span role="status">{hovered?`${hovered.name} · ${size(hovered.bytes)} · ${total?(hovered.bytes/total*100).toFixed(1):0}%`:groups.length?'正在查看小项，点击上一级返回。':''}</span>{others&&small(map.find(o=>o.other))&&<button className="text-button" onClick={openGroup}>查看{others.name}</button>}</div>
 <p className="space-note">{mode==='tree'?'点击查看子目录；末级目录可展开文件。图中占比仅计算子目录。':'只展示本次扫描最大的200个文件，不等于所有文件。'}{task.status!=='succeeded'?' 当前统计尚不完整，大小仅为已读取结果。':''}{task.tree_truncated?' 部分目录未显示，请选择较小的范围重新统计。':''}</p>
 <div className="space-table" role="table" aria-label="空间大小排序"><div className="space-table-row space-table-heading" role="row"><button onClick={()=>setSort('name')}>名称</button><button onClick={()=>setSort('bytes')}>逻辑大小 ↓</button><button onClick={()=>setSort('files')}>文件数</button><span>占比</span></div>{rows.map(o=><React.Fragment key={o.path}><div className="space-table-row" role="row"><button className="space-name" title={o.path} aria-expanded={mode==='tree'&&leaf(o.path)?expanded===o.path:undefined} onClick={()=>mode==='tree'?choose(o.path):(tree.some(n=>n.path===o.parent)?(setMode('tree'),navigate(o.parent)):onBrowse?.(o.parent))}>{mode==='tree'?<Folder size={15}/>:<File size={15}/>}<span>{o.name}</span><ChevronRight size={13} className={expanded===o.path?"expanded-chevron":""}/></button><span>{measured(o)}</span><span>{!complete(o)&&!o.files?'—':mode==='tree'?o.files:'—'}</span><span>{!complete(o)&&!o.bytes?'—':`${total?((o.bytes/total)*100).toFixed(1):'0'}%`}</span></div>{mode==='tree'&&expanded===o.path&&<DirectoryFiles path={o.path} post={post} includeDirectories={!complete(o)} onBrowse={onBrowse}/>}</React.Fragment>)}</div>
 </div>}
 </section>;
}
