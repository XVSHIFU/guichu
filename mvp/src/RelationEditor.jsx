import React,{useEffect,useId,useRef,useState} from 'react';
import {ArrowRight,Check,Link2,LoaderCircle,RefreshCw,Search,Trash2,X} from 'lucide-react';
import './relation-editor.css';

export default function RelationEditor({object,objects=[],post,onChanged,offline=false,setBusy:setParentBusy}){
 const [relations,setRelations]=useState([]),[query,setQuery]=useState(''),[selected,setSelected]=useState(null),[label,setLabel]=useState(''),[busy,setBusy]=useState(''),[loaded,setLoaded]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const epoch=useRef(0),locked=useRef(false),postRef=useRef(post),currentId=useRef(object?.id),parentBusy=useRef(setParentBusy),searchRef=useRef(null),labelRef=useRef(null),prefix=useId();
 postRef.current=post;currentId.current=object?.id;parentBusy.current=setParentBusy;
 const id=object?.id,disabled=!!busy||offline,selectedObject=objects.find(item=>item.id===selected?.id),search=query.trim().toLocaleLowerCase();
 const matches=search?objects.filter(item=>item.id!==id&&[item.name,item.path,item.kind].some(value=>String(value||'').toLocaleLowerCase().includes(search))):[];
 const visible=relations.filter(item=>item.from===id||item.to===id);
 const name=objectId=>objects.find(item=>item.id===objectId)?.name||`未收录对象 · ${objectId}`;
 async function read(version,targetId){const result=await postRef.current('relation/list',{});if(epoch.current===version&&currentId.current===targetId){setRelations(result.relations||[]);setLoaded(true)}}
 async function perform(kind,work){if(locked.current||offline||!id)return;const version=epoch.current,targetId=id;locked.current=true;setBusy(kind);setError('');setNotice('');if(kind!=='load')parentBusy.current?.(true);try{await work(version,targetId)}catch(e){if(epoch.current===version&&currentId.current===targetId)setError(e.message||'关联操作未完成，请重试。')}finally{if(epoch.current===version){locked.current=false;setBusy('');if(kind!=='load')parentBusy.current?.(false)}}}
 useEffect(()=>{const version=++epoch.current;locked.current=false;setRelations([]);setQuery('');setSelected(null);setLabel('');setLoaded(false);setBusy('');setError('');setNotice('');if(!offline)perform('load',read);return()=>{if(epoch.current===version){epoch.current++;parentBusy.current?.(false)}}},[id]);
 useEffect(()=>{if(!offline&&!loaded&&!locked.current)perform('load',read)},[offline]);
 function add(event){event.preventDefault();if(disabled||!selectedObject||!label.trim()||label.trim().length>80)return;const target=selectedObject.id,description=label.trim();perform('add',async(version,source)=>{const result=await postRef.current('relation/add',{from_id:source,to_id:target,label:description});if(epoch.current!==version||currentId.current!==source)return;setRelations(previous=>[...previous.filter(item=>item.id!==result.relation.id),result.relation]);setSelected(null);setQuery('');setLabel('');setNotice('人工关联已保存。');await onChanged?.(source);if(epoch.current===version)searchRef.current?.focus()})}
 function remove(relation){if(disabled)return;perform('remove:'+relation.id,async(version,source)=>{await postRef.current('relation/remove',{id:relation.id});if(epoch.current!==version||currentId.current!==source)return;setRelations(previous=>previous.filter(item=>item.id!==relation.id));setNotice('人工关联已移除，扫描发现的关系仍保留。');await onChanged?.(source);if(epoch.current===version)searchRef.current?.focus()})}
 return <section className="detail-section relation-editor" aria-labelledby={prefix+'-heading'}>
  <div className="relation-editor-heading"><h3 id={prefix+'-heading'}>人工关联</h3><button type="button" className="text-button" disabled={disabled} onClick={()=>perform('load',read)}><RefreshCw size={13}/>刷新关联</button></div>
  <p className="relation-editor-help">补充你确认的对象关系。只保存在工作台，不改动工具配置。</p>
  <form onSubmit={add}>
   <label htmlFor={prefix+'-search'}>关联到哪个对象</label>
   {selected?<div className="relation-editor-selected"><Link2 size={16}/><span><strong>{selectedObject?.name||selected.name}</strong><small>{selectedObject?.path||(!selectedObject?'该对象已不在当前清单，请重新选择':selectedObject.kind)}</small></span><button type="button" className="icon-button" aria-label="重新选择关联对象" disabled={disabled} onClick={()=>{setSelected(null);setQuery('');requestAnimationFrame(()=>searchRef.current?.focus())}}><X size={15}/></button></div>:<>
    <div className="relation-editor-search"><Search size={15}/><input ref={searchRef} id={prefix+'-search'} value={query} onChange={event=>setQuery(event.target.value)} disabled={disabled} placeholder="搜索名称或路径" autoComplete="off" aria-describedby={prefix+'-search-status'}/></div>
    {search&&<div className="relation-editor-results" aria-label="关联对象搜索结果">{matches.slice(0,30).map(item=><button type="button" key={item.id} disabled={disabled} aria-label={'选择 '+item.name} onClick={()=>{setSelected({id:item.id,name:item.name});setNotice('');labelRef.current?.focus()}}><span><strong>{item.name}</strong><small>{item.path||item.kind}</small></span><ArrowRight size={14}/></button>)}</div>}
    <p id={prefix+'-search-status'} className="relation-editor-hint" aria-live="polite">{search?matches.length?matches.length>30?`找到 ${matches.length} 项，先显示 30 项；可继续输入缩小范围。`:`找到 ${matches.length} 个对象。`:'没有匹配对象，可换个名称或路径。':'仅从当前清单选择，不能关联对象自身。'}</p>
   </>}
   <label htmlFor={prefix+'-label'}>关联说明</label><input ref={labelRef} id={prefix+'-label'} value={label} onChange={event=>setLabel(event.target.value)} disabled={disabled} maxLength={80} placeholder="例如：项目使用的工具"/>
   <button type="submit" className="button primary" disabled={disabled||!loaded||!selectedObject||!label.trim()}>{busy==='add'?<LoaderCircle size={15} className="spin"/>:<Check size={15}/>}保存人工关联</button>
  </form>
  {offline&&<p className="relation-editor-feedback" role="status">本地服务离线，人工关联暂不可修改。</p>}
  {busy==='load'&&<p className="relation-editor-feedback" role="status">正在读取人工关联…</p>}
  {error&&<div className="relation-editor-feedback relation-editor-error" role="alert">{error}<button type="button" className="text-button" disabled={disabled} onClick={()=>perform('load',read)}>重新读取</button></div>}
  {notice&&<p className="relation-editor-feedback" role="status">{notice}</p>}
  <div className="relation-editor-list" aria-label="已保存的人工关联">{loaded&&!visible.length?<p className="relation-editor-hint">此对象还没有人工关联。</p>:visible.map(relation=><div className="relation-editor-row" key={relation.id}><div><div className="relation-editor-endpoints"><span>{name(relation.from)}</span><ArrowRight size={13} aria-label="关联到"/><span>{name(relation.to)}</span></div><strong>{relation.label}</strong>{relation.missing&&<small>部分对象未在当前清单中，记录已保留。</small>}</div><button type="button" className="icon-button" disabled={disabled} aria-label={'移除人工关联：'+relation.label} onClick={()=>remove(relation)}>{busy==='remove:'+relation.id?<LoaderCircle size={15} className="spin"/>:<Trash2 size={15}/>}</button></div>)}</div>
 </section>
}
