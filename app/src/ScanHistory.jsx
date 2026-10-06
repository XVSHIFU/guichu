import React,{useState} from 'react';
import {Check,AlertCircle,Clock3,LoaderCircle,RefreshCw} from 'lucide-react';
import './scan-history.css';

const labels={queued:'等待检查',running:'正在检查',succeeded:'检查完成',partial:'部分完成',failed:'检查失败',interrupted:'检查中断'};
const active=task=>['queued','running'].includes(task?.status);
const date=value=>{if(!value)return '时间未记录';const parsed=new Date(value);return Number.isNaN(parsed.valueOf())?'时间未记录':parsed.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false})};
function summary(task){
 if(typeof task.source_summary==='string')return task.source_summary;
 const info=task.source_summary;
 if(info&&typeof info==='object')return [['total','个来源'],['succeeded','个来源完成'],['failed','个来源失败'],['retained','个来源保留旧记录']].filter(([key])=>Number.isFinite(info[key])).map(([key,label])=>`${info[key]} ${label}`).join(' · ');
 const sources=Array.isArray(task.sources)?task.sources:Object.values(task.sources||{});
 if(!sources.length)return '';
 const failed=sources.filter(source=>['failed','partial','error'].includes(typeof source==='string'?source:source?.status)).length;
 return `${sources.length} 个来源${failed?` · ${failed} 个来源未完整读取`:''}`;
}

export default function ScanHistory({tasks=[],current,offline=false,onRefresh}){
 const [visible,setVisible]=useState(10);
 const [retrying,setRetrying]=useState(false),[error,setError]=useState('');
 const items=[...tasks].sort((a,b)=>String(b.started_at||b.created_at||'').localeCompare(String(a.started_at||a.created_at||'')));
 const currentTask=current?.task||current;
 const running=!!current?.running||active(currentTask)||items.some(active);
 const showCurrent=(current?.running||active(currentTask))&&!items.some(item=>active(item)||(currentTask?.id&&item.id===currentTask.id));
 const retryable=items.some(item=>['partial','failed','interrupted'].includes(item.status))||!!current?.error;
 async function retry(){if(offline||running||retrying)return;setRetrying(true);setError('');try{await onRefresh?.()}catch(e){setError(e.message||'检查未能开始，请重试。')}finally{setRetrying(false)}}
 return <section className="scan-history" aria-labelledby="scan-history-title"><div className="scan-history-heading"><div><h2 id="scan-history-title">检查任务</h2><p>查看最近检查的完成情况；可展开查看检查范围和未完成项。</p></div>{retryable&&<button type="button" className="button" disabled={offline||running||retrying||!onRefresh} onClick={retry}>{retrying?<LoaderCircle size={14} className="spin"/>:<RefreshCw size={14}/>}重新检查</button>}</div>
 {offline&&<p className="scan-history-note">本地服务离线，当前显示最近收到的检查记录。</p>}{error&&<p className="scan-history-error" role="alert">{error}</p>}
 {showCurrent&&<div className="scan-history-current" role="status"><LoaderCircle size={15} className="spin"/><span>{currentTask?.status==='queued'?'等待检查':'正在检查'}{currentTask?.started_at?' · '+date(currentTask.started_at):''}</span></div>}
 {!items.length&&!showCurrent?<p className="scan-history-empty">还没有检查任务记录。</p>:<ol className="scan-history-list">{items.slice(0,visible).map((task,index)=>{const sources=summary(task),count=task.object_count??task.count;return <li key={task.id||task.started_at||index} className={'scan-history-item scan-'+task.status}><span className="scan-history-symbol" aria-hidden="true">{active(task)?<LoaderCircle size={15} className="spin"/>:task.status==='succeeded'?<Check size={15}/>:['partial','failed','interrupted'].includes(task.status)?<AlertCircle size={15}/>:<Clock3 size={15}/>}</span><div className="scan-history-body"><div className="scan-history-row"><strong>{labels[task.status]||'状态未记录'}</strong><time dateTime={task.started_at||undefined}>开始 {date(task.started_at)}</time></div><details><summary>查看详情{task.issue_count>0?` · ${task.issue_count} 项未完成`:""}</summary>{(sources||Number.isFinite(count))&&<p>{Number.isFinite(count)?`${count} 个对象`:''}{Number.isFinite(count)&&sources?' · ':''}{sources}</p>}{task.issue_count>0&&<p>{task.issue_count} 项未完成检查</p>}{task.status==='partial'&&<p className="scan-history-caveat">未完整读取的来源会保留已有记录，不据此认定对象已移除。</p>}{task.status==='interrupted'&&<p className="scan-history-caveat">任务未正常结束，本次检查不能视为完整结果。</p>}{task.error&&<p className="scan-history-error">{typeof task.error==='string'?task.error:'检查遇到错误。'}</p>}{task.finished_at&&<small>结束 {date(task.finished_at)}</small>}</details></div></li>})}</ol>}{visible<items.length&&<button className="button" onClick={()=>setVisible(n=>n+10)}>显示更多检查记录</button>}
 </section>
}
