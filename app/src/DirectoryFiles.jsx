import React,{useEffect,useRef,useState} from 'react';
import {File,Folder,LoaderCircle,ExternalLink,FolderOpen,Copy} from 'lucide-react';

const openable=path=>/\.(txt|md|markdown|json|yaml|yml|toml|ini|log|csv|tsv|pdf|doc|docx|xls|xlsx|ppt|pptx|odt|ods|rtf|png|jpg|jpeg|gif|webp|bmp|svg|mp3|wav|mp4|mkv|mov)$/i.test(path);
const runnable=path=>/\.(exe|com|bat|cmd|ps1|py|js|vbs|msi|scr|lnk)$/i.test(path);
export default function DirectoryFiles({path,post,includeDirectories=false,onBrowse}){
 const [result,setResult]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [selected,setSelected]=useState(null),[feedback,setFeedback]=useState(''),[acting,setActing]=useState(false);
 async function operate(action,file){if(acting)return;setActing(true);setFeedback('');try{if(action==='copy'){await navigator.clipboard.writeText(file.path);setFeedback('路径已复制')}else{await postRef.current('file-action',{action,path:file.path});setFeedback(action==='open'?'已交给默认应用打开':'已在文件夹中显示')}}catch(e){setFeedback(e.message||'操作未完成，请重试')}finally{setActing(false)}}
 const sequence=useRef(0),postRef=useRef(post),locked=useRef(false);postRef.current=post;
 async function load(cursor){
  if(locked.current)return;
  locked.current=true;const token=++sequence.current;setBusy(true);setError('');
  try{const next=await postRef.current('browse',{path,mode:includeDirectories?'全部':'文件',...(cursor?{cursor}:{})});
   if(token===sequence.current)setResult(previous=>({...next,entries:cursor?[...(previous?.entries||[]),...next.entries]:next.entries}));
  }catch(e){if(token===sequence.current)setError(e.message||'无法读取文件列表。')}
  finally{if(token===sequence.current){locked.current=false;setBusy(false)}}
 }
 useEffect(()=>{setResult(null);locked.current=false;load();return()=>{sequence.current++;locked.current=false}},[path]);
 return <div className="space-inline-files" role="region" aria-label="目录内文件"><p className="space-note">{includeDirectories?'目录内容':'文件'}{result?` · 已显示 ${result.entries.length} / ${result.total} 项`:''}</p>
 {!includeDirectories&&result?.directoryCount>0&&<p className="space-note">此目录还包含子文件夹；若目录树中未显示，请重新统计。</p>}
 {result?.read_errors>0&&<p role="status" className="space-note">有 {result.read_errors} 项未能读取，列表可能不完整。</p>}
 {feedback&&<p className="space-note" role="status">{feedback}</p>}
 <ul>{result?.entries.map(file=><li key={file.path} title={file.path}><button className="inline-file-name" aria-pressed={selected===file.path} onClick={()=>{if(file.directory&&!file.link){onBrowse?.(file.path);return}setSelected(file.path);setFeedback('')}}>{file.directory?<Folder size={14}/>:<File size={14}/>}<span>{file.name}</span></button>{file.link&&<small>链接</small>}{selected===file.path&&<div className="inline-file-actions">{(openable(file.path)||runnable(file.path))&&<button className="text-button" disabled={acting||file.link} onClick={()=>operate(runnable(file.path)?'reveal':'open',file)}><ExternalLink size={13}/>{runnable(file.path)?'在文件夹中运行':'打开'}</button>}<button className="text-button" disabled={acting} onClick={()=>operate('reveal',file)}><FolderOpen size={13}/>在文件夹中显示</button><button className="text-button" disabled={acting} onClick={()=>operate('copy',file)}><Copy size={13}/>复制路径</button></div>}</li>)}</ul>
 {!busy&&!error&&result?.total===0&&<p className="space-note">此目录没有可列出的文件。</p>}
 {busy&&<p className="space-note" role="status"><LoaderCircle size={14} className="spin"/>正在读取文件…</p>}
 {error&&<p className="space-note" role="alert">{error} <button className="text-button" onClick={()=>load()}>重新读取</button></p>}
 {result?.next&&!busy&&!error&&<button className="text-button" onClick={()=>load(result.next)}>加载更多文件</button>}
 </div>;
}
