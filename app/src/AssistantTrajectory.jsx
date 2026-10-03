import React,{useMemo,useState,useEffect} from 'react';
import {ArrowLeft,ChevronRight,CheckCircle2,AlertCircle,Clock,FileText,Wrench,Search,Rows3,ListTree} from 'lucide-react';
import MarkdownMessage from './MarkdownMessage';
import {trajectorySteps,trajectoryTimeline,recordedDuration,runStates} from './trajectory';
import './assistant-trajectory.css';

function time(value){if(!value||!Number.isFinite(Date.parse(value)))return '未记录';return new Date(value).toLocaleString('zh-CN',{hour12:false});}
export default function AssistantTrajectory({run,events,selectedId,onSelect,onBack,buttonRef,historical,onLatest,disabled}) {
  const steps=useMemo(()=>trajectorySteps(events,run?.status),[events,run?.status]);
  const [query,setQuery]=useState(''),[actualDuration,setActualDuration]=useState(false),[foldTurn,setFoldTurn]=useState(false),[foldCalls,setFoldCalls]=useState(false);
  useEffect(()=>{setQuery('');setFoldTurn(false);setFoldCalls(false)},[run?.id]);
  const matched=steps.filter(step=>[step.title,step.name,step.label,step.text,...step.events.map(e=>e.message||e.error)].filter(Boolean).join(' ').toLowerCase().includes(query.trim().toLowerCase()));
  const visible=matched.filter(step=>!foldCalls||step.kind!=='tool');
  const spans=useMemo(()=>trajectoryTimeline(steps,actualDuration),[steps,actualDuration]);
  const selected=steps.find(step=>step.id===selectedId);
  if(selected)return <section className="assistant-trajectory trajectory-detail">
    <button type="button" className="text-button" onClick={()=>onBack(selected.id)}><ArrowLeft size={14}/>返回轨迹</button>
    <h3>{selected.title}</h3><p className="trajectory-detail-state" data-state={selected.state}>{selected.label}</p>
    <dl><div><dt>类型</dt><dd>{selected.kind==='tool'?'工具调用':selected.kind==='text'?'模型输出':'任务事件'}</dd></div>
      {selected.name&&<div><dt>工具</dt><dd><code>{selected.name}</code></dd></div>}
      <div><dt>记录序号</dt><dd>{selected.events.map(e=>e.seq).filter(v=>v!=null).join('、')||'未记录'}</dd></div>
      <div><dt>开始记录</dt><dd>{time(selected.start)}</dd></div>
      {selected.end&&<div><dt>结束记录</dt><dd>{time(selected.end)}</dd></div>}
      {selected.kind==='tool'&&recordedDuration(selected.start,selected.end)&&<div><dt>用时</dt><dd>{recordedDuration(selected.start,selected.end)}</dd></div>}
    </dl>
    {selected.kind==='tool'&&(selected.events.some(e=>e.arguments!==undefined||e.result!==undefined)?selected.events.filter(e=>e.arguments!==undefined||e.result!==undefined).map(e=><div key={e.seq}><h4>{e.arguments!==undefined?'调用输入':'返回内容'}</h4><pre className="trajectory-raw">{JSON.stringify(e.arguments??e.result,null,2)}</pre></div>):<p className="trajectory-note">这条早期记录未保存调用参数或结果正文。</p>)}
    {selected.text&&<MarkdownMessage text={selected.text}/>}
    {selected.events.filter(e=>e.message||e.error).map((e,i)=><p key={i}>{typeof (e.message||e.error)==='string'?(e.message||e.error):'此事件记录了错误，详见原始记录。'}</p>)}
    <details className="trajectory-raw"><summary>查看原始记录</summary><pre>{JSON.stringify(selected.events,null,2)}</pre></details>
  </section>;
  return <section className="assistant-trajectory" aria-label="分析轨迹">
    <div className="trajectory-heading"><h3>分析轨迹</h3>{run&&<span>{runStates[run.status]||run.status}</span>}</div>
    {!run?<p className="trajectory-note">发送请求后，这里会按顺序记录模型输出与工具调用。</p>:<>
      <p className="trajectory-scope">{run.target?.name||run.target?.id||'清单范围'}</p>
      {(run.provider_name||run.model)&&<p className="trajectory-note">{[run.provider_name,run.model].filter(Boolean).join(' · ')}</p>}
      {historical&&<button type="button" className="text-button" disabled={disabled} onClick={onLatest}>查看最新轨迹</button>}
      {run.error&&<p className="assistant-run-error">{typeof run.error==='string'?run.error:'分析未完成，请检查连接设置。'}</p>}
      <div className="trajectory-controls" role="group" aria-label="轨迹显示">
        <button type="button" aria-label="按记录时长排列" aria-pressed={actualDuration} onClick={()=>setActualDuration(v=>!v)} title="切换实际记录时间与等宽步骤"><Clock size={12}/>时长</button>
        <button type="button" aria-label={foldTurn?'展开本次请求':'折叠本次请求'} aria-pressed={foldTurn} onClick={()=>setFoldTurn(v=>!v)} title="本次请求的轨迹；未记录模型内部轮次"><Rows3 size={12}/>轮次</button>
        <button type="button" aria-label={foldCalls?'展开工具调用':'折叠工具调用'} aria-pressed={foldCalls} onClick={()=>setFoldCalls(v=>!v)}><ListTree size={12}/>调用</button>
        <label className="trajectory-search"><Search size={12}/><input type="search" aria-label="搜索轨迹" placeholder="搜索" value={query} onChange={e=>{setQuery(e.target.value);setFoldTurn(false)}}/></label>
      </div>
      <div className="trajectory-overview" aria-label={actualDuration?'真实记录时间带':'等宽步骤概览'}>
        {[['event','事件'],['text','助手'],['tool','工具']].map(([kind,label])=><div className="trajectory-lane" key={kind}><span>{label}</span><div>{spans.filter(span=>span.kind===kind).map(span=>{const step=steps.find(s=>s.id===span.id);return <button type="button" key={span.id} className="trajectory-span" data-kind={kind} data-dimmed={!matched.includes(step)} style={{left:`min(calc(100% - 4px), ${span.left}%)`,width:actualDuration?`max(4px, ${span.width}%)`:`max(3px, calc(${span.width}% - 2px))`}} aria-label={`查看${step.title}详情`} title={`${step.title} · ${step.label}${recordedDuration(step.start,step.end)?' · '+recordedDuration(step.start,step.end):''}`} onClick={()=>{setQuery('');setFoldTurn(false);setFoldCalls(false);onSelect(step.id)}}/>})}</div></div>)}
      </div>
      {actualDuration&&<p className="trajectory-timing-note">{spans.length?`按已记录时间排列${spans.length<steps.length?'；无时间的步骤未绘入时间带':''}。`:'这些记录没有有效时间，无法绘制时长。'}</p>}
      <div className="trajectory-ledger-heading"><span>本次请求</span><span>轨迹步骤 · {steps.length}</span></div>
      {query&&<p className="trajectory-filter-count" role="status">匹配 {matched.length} 项{foldCalls?' · 工具调用已折叠':''}</p>}
      {foldTurn&&<p className="trajectory-note">已折叠本次请求，点击“轮次”展开。</p>}
      {!foldTurn&&!visible.length&&steps.length>0&&<p className="trajectory-note">{matched.length?'工具调用已折叠。':'没有匹配的轨迹。'}</p>}
      {!steps.length&&<p className="trajectory-note">尚无已保存的轨迹记录。</p>}
      <ol className="trajectory-steps trajectory-ledger" hidden={foldTurn}>{visible.map(step=>{
        const Icon=['failed','cancelled','interrupted','incomplete'].includes(step.state)?AlertCircle:step.state==='running'?Clock:step.kind==='tool'?Wrench:step.kind==='text'?FileText:step.state==='succeeded'?CheckCircle2:Clock;
        const duration=step.kind==='tool'?recordedDuration(step.start,step.end):null;
        return <li key={step.id} data-state={step.state}><span className="trajectory-marker" aria-hidden="true"><Icon size={14}/></span>
          <button type="button" ref={node=>buttonRef(step.id,node)} onClick={()=>onSelect(step.id)}>
            <span className="trajectory-step-title"><b className="trajectory-kind" data-kind={step.kind}>{step.kind==='tool'?'工具':step.kind==='text'?'助手':'事件'}</b>{step.title}</span><ChevronRight size={13}/>
            <small>{step.label}{duration&&` · ${duration}`}</small>
            {step.text&&<span className="trajectory-excerpt">{step.text}</span>}
            {step.name&&step.name!==step.title&&<code>{step.name}</code>}
          </button></li>;
      })}</ol>
    </>}
  </section>;
}
