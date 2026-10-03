import React,{useEffect,useState,useRef} from 'react';
import {ChevronDown,Wrench,Copy,Check} from 'lucide-react';
import MarkdownMessage from './MarkdownMessage';
import './execution-process.css';

const statuses={queued:'等待开始',running:'正在执行',succeeded:'已完成',awaiting_confirmation:'等待确认',failed:'执行失败',cancelled:'已停止',interrupted:'已中断'};
const toolNames={load_skill:'加载技能',inspect_config:'检查配置',propose_change:'生成变更提案',propose_restore:'生成恢复提案',read_config_summary:'读取配置摘要',read_file:'读取文件',list_directory:'查看目录',list_directory_names:'查看目录名称',search_objects:'搜索清单',get_object:'读取对象详情',get_relations:'读取关联关系',propose_mcp_toggle:'生成 MCP 配置提案',propose_decision:'生成保留决定提案'};
const stringify=value=>typeof value==='string'?value:JSON.stringify(value,null,2);
export function processSteps(events){
 const rows=[],calls=new Map();
 for(const e of events){
  if(e.type==='tool_started'){const row={...e,kind:'tool',key:e.call_id||`legacy-${e.seq}`,done:false};rows.push(row);calls.set(row.key,row)}
  else if(e.type==='tool_finished'){const row=e.call_id?calls.get(e.call_id):[...rows].reverse().find(r=>r.kind==='tool'&&!r.done&&(r.name===e.name||r.tool===e.tool));if(row){Object.assign(row,{done:true,result:e.result,error:e.error||(e.ok===false?'工具调用失败':null),finish:e,cached:e.cached})}else rows.push({...e,kind:'tool',key:e.call_id||`legacy-${e.seq}`,done:true})}
  else if(e.type==='text'&&e.channel==='intermediate'){const last=rows.at(-1);if(last?.kind==='text'&&last.round_id===e.round_id)last.text+=e.text||'';else rows.push({...e,key:`text-${e.seq}`,kind:'text',text:e.text||''})}
  else if(e.type==='error')rows.push({...e,key:`error-${e.seq}`,kind:'error'});
 }return rows;
}
function RecordedContent({value}){const [copied,setCopied]=useState(false),[error,setError]=useState('');async function copy(){try{await navigator.clipboard.writeText(stringify(value));setCopied(true);setError('')}catch{setError('复制失败，请选择内容复制。')}}return <div className="execution-recorded"><button type="button" className="text-button" onClick={copy}>{copied?<Check size={12}/>:<Copy size={12}/>} {copied?'已复制':'复制'}</button>{error&&<p role="alert">{error}</p>}<pre>{stringify(value)}</pre></div>}
export default function ExecutionProcess({runId,run:liveRun,events:liveEvents,post,offline=false}){
 const manual=useRef(false);const [open,setOpen]=useState(()=>['queued','running'].includes(liveRun?.status)),[record,setRecord]=useState(null),[events,setEvents]=useState([]),[error,setError]=useState(''),[loading,setLoading]=useState(false);
 const live=liveRun?.id===runId,run=live?liveRun:record,source=live?liveEvents:events;
 useEffect(()=>{if(!open||live||offline||record)return;let stopped=false;setLoading(true);setError('');(async()=>{let after=0,all=[],r;for(;;){const result=await post('run/get',{id:runId,after});r=result.run;if(r.id!==runId)throw Error('运行记录不匹配');const page=result.events||[];all.push(...page);if(page.length<500)break;const next=Math.max(...page.map(e=>e.seq||0));if(next<=after)throw Error('运行记录读取未完成');after=next}if(!stopped){setRecord(r);setEvents(all)}})().catch(e=>{if(!stopped)setError(e.message)}).finally(()=>{if(!stopped)setLoading(false)});return()=>{stopped=true}},[open,live,offline,runId,record,post]);
 useEffect(()=>{if(!manual.current)setOpen(['queued','running'].includes(run?.status))},[run?.status]);
 const duration=run?.created_at&&run?.updated_at&&!['queued','running'].includes(run?.status)?Date.parse(run.updated_at)-Date.parse(run.created_at):null;
 const rows=processSteps(source||[]),count=rows.filter(r=>r.kind==='tool').length;
 return <section className="execution-process"><button type="button" className="execution-disclosure" aria-expanded={open} onClick={()=>{manual.current=true;setOpen(v=>!v)}}><ChevronDown size={14}/><span>{statuses[run?.status]||'执行过程'}</span>{duration!==null&&Number.isFinite(duration)&&duration>=0&&<small>用时 {(duration/1000).toFixed(1)} 秒</small>}{count>0&&<small>{count} 次工具调用</small>}</button>{open&&<div className="execution-body">{loading&&<p>正在读取执行记录…</p>}{error&&<p role="alert">{error}</p>}{!loading&&!error&&!rows.length&&<p>这次运行没有保存可展开的工具内容。</p>}{rows.map(row=>row.kind==='text'?<div className="execution-intermediate" key={row.key}><MarkdownMessage text={row.text}/></div>:row.kind==='error'?<p role="alert" key={row.key}>{row.message||row.error||'运行未完成'}</p>:<details className="execution-tool" key={row.key}><summary><Wrench size={13}/><span>{toolNames[row.name||row.tool]||row.name||row.tool||'工具调用'}</span><small>{row.error?'失败':row.done?(row.cached?'复用本次结果':'已返回'):['running','queued'].includes(run?.status)?'进行中':'未记录结果'}</small></summary><div className="execution-tool-body">{row.round_id!=null&&<p>轮次 {row.round_id}</p>}{row.arguments!==undefined?<><h4>输入</h4><RecordedContent value={row.arguments}/></>:<p>早期记录未保存调用参数。</p>}{row.result!==undefined&&<><h4>返回内容</h4><RecordedContent value={row.result}/></>}{row.error&&<p role="alert">{stringify(row.error)}</p>}</div></details>)}</div>}</section>;
}
