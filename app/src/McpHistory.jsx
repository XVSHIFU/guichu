import React,{useEffect,useId,useRef,useState} from 'react';
import {History,RefreshCw} from 'lucide-react';
import McpActionPanel from './McpActionPanel';
import './mcp-history.css';

const states={pending:'待确认',applying:'正在修改',applied:'已修改',restoring:'正在恢复',restored:'已恢复',conflict:'配置冲突',failed:'操作失败',interrupted:'操作中断',restore_conflict:'恢复冲突'};

export default function McpHistory({post,offline=false,onChanged,onOpenSession}){
 const titleId=useId(),[actions,setActions]=useState([]),[selected,setSelected]=useState(null),[loading,setLoading]=useState(false),[loaded,setLoaded]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const sequence=useRef(0),postRef=useRef(post);postRef.current=post;
 const action=actions.find(item=>item.id===selected);
 async function refresh(){
  if(offline)return;
  const id=++sequence.current;setLoading(true);setError('');
  try{const result=await postRef.current('mcp-action/list',{});if(id!==sequence.current)return;const next=result.actions||[];setActions(next);setLoaded(true);setSelected(previous=>next.some(item=>item.id===previous)?previous:null)}
  catch(e){if(id===sequence.current)setError(e.message||'配置历史暂时无法读取，请重试。')}
  finally{if(id===sequence.current)setLoading(false)}
 }
 useEffect(()=>{refresh();return()=>{sequence.current++}},[offline]);
 async function changed(){await refresh();await onChanged?.()}
 const snapshot=action?{kind:'mcp',scope:'codex',source:'用户配置',...action.object,path:action.object?.path||action.path}:null;
 return <section className="mcp-global-history" aria-labelledby={titleId}>
  <div className="mcp-global-heading"><h2 id={titleId}><History size={17}/>配置操作历史</h2><button type="button" className="text-button" disabled={offline||loading||busy} onClick={refresh}><RefreshCw size={14} className={loading?'spin':''}/>刷新配置历史</button></div>
  <p className="muted">保留每次 MCP 修改的对象快照和备份记录。对象已从清单消失时，仍可在这里核对结果并尝试恢复。</p>
  {offline&&<p role="status" className="mcp-global-feedback">本地服务离线，暂不可读取或恢复配置。</p>}
  {loading&&!loaded&&<p role="status" className="mcp-global-feedback">正在读取配置历史…</p>}
  {error&&<p role="alert" className="mcp-global-feedback">{error}{loaded?' 当前显示上次读取的记录。':''}</p>}
  {loaded&&!actions.length&&<p className="mcp-global-feedback">还没有 MCP 配置操作记录。</p>}
  <div className="mcp-global-records">{actions.map(item=><button type="button" key={item.id} className="mcp-global-record" disabled={busy} aria-current={selected===item.id?'true':undefined} onClick={()=>setSelected(item.id)}><span><strong>{item.object?.name||item.server_id||'历史 MCP'}</strong><small>{item.path||item.object?.path||'未记录路径'}</small></span><span className="mcp-global-state">{states[item.state]||item.state}{item.created_at&&<time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString('zh-CN')}</time>}</span></button>)}</div>
  {action&&<div className="mcp-global-detail"><McpActionPanel key={action.id} object={snapshot} post={post} offline={offline} onChanged={changed} onOpenSession={onOpenSession} setBusy={setBusy} historyOnly initialActionId={action.id}/></div>}
 </section>
}
