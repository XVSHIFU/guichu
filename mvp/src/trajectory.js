const terminal = new Set(['succeeded','failed','cancelled','interrupted','awaiting_confirmation']);
export const runStates = {awaiting_confirmation:'等待确认',queued:'等待分析',running:'正在分析',succeeded:'分析完成',failed:'分析失败',cancelled:'已取消',interrupted:'已中断'};
const toolNames = {load_skill:'加载技能',inspect_config:'检查配置',get_action_capabilities:'检查支持的操作',propose_change:'生成修改提案',propose_restore:'生成恢复提案',propose_categories:'生成分类提案',measure_directory:'统计目录大小',search_objects:'搜索清单对象',get_object:'读取对象详情',get_relations:'读取关联关系',read_config_summary:'读取配置摘要',list_directory:'查看目录内容',list_directory_names:'查看目录名称'};
export function recordedDuration(start,end) {
  if(!start||!end)return null;
  const ms=Date.parse(end)-Date.parse(start);
  return Number.isFinite(ms)&&ms>=0 ? (ms<1000?`${ms} 毫秒`:`${(ms/1000).toFixed(1)} 秒`) : null;
}
// Position only timestamps actually stored by the runtime; missing timing has no span.
export function trajectoryTimeline(steps,actualDuration=false) {
  if(!actualDuration)return steps.map((step,index)=>({id:step.id,kind:step.kind,left:index/Math.max(1,steps.length)*100,width:100/Math.max(1,steps.length)}));
  const timed=steps.map(step=>({step,start:Date.parse(step.start||step.end),end:Date.parse(step.end||step.start)})).filter(v=>Number.isFinite(v.start)&&Number.isFinite(v.end)&&v.end>=v.start);
  if(!timed.length)return [];
  const start=Math.min(...timed.map(v=>v.start)),end=Math.max(...timed.map(v=>v.end)),span=Math.max(1,end-start);
  return timed.map(v=>({id:v.step.id,kind:v.step.kind,left:(v.start-start)/span*100,width:(v.end-v.start)/span*100}));
}
export function trajectorySteps(events=[],status) {
  const steps=[],pending=new Map(),seen=new Set();
  const ordered=[...events].sort((a,b)=>(a.seq??0)-(b.seq??0));
  for(const event of ordered) {
    if(event.seq!=null&&seen.has(event.seq))continue;
    seen.add(event.seq);
    const id=event.seq??`event-${steps.length}`,name=event.name||event.tool||'未命名工具';
    if(event.type==='tool_finished') {
      // Runtime executes tools serially and records names, not call IDs.
      const queue=pending.get(event.call_id||name)||[],step=queue.shift();
      const finished=step||{id,kind:'tool',title:toolNames[name]||name,name,events:[]};
      finished.events.push(event);finished.end=event.at;
      finished.state=event.ok===false?'failed':event.ok===true?'succeeded':'unknown';
      finished.label=event.ok===false?'调用失败':event.ok===true?(event.cached?'复用本次查询结果':'已完成'):'已返回，状态未记录';
      if(!step)steps.push(finished);
      continue;
    }
    if(event.type==='text'||event.type==='final_answer') {
      const last=steps.at(-1);
      if(last?.kind==='text'&&last.events.at(-1)?.type===event.type&&last.events.at(-1)?.round_id===event.round_id){last.events.push(event);last.text+=event.text||'';last.end=event.at;continue;}
      steps.push({id,kind:'text',title:event.channel==='intermediate'?'执行过程说明':event.type==='final_answer'?'最终回复':'模型回答',label:'已记录输出',state:'recorded',text:event.text||'',start:event.at,end:event.at,events:[event]});continue;
    }
    const step={id,kind:event.type==='tool_started'?'tool':'event',start:event.at,events:[event],state:'recorded'};
    if(event.type==='tool_started') {
      Object.assign(step,{title:toolNames[name]||name,name,label:terminal.has(status)?'未记录完成结果':'正在调用',state:terminal.has(status)?'incomplete':'running'});
      const queue=pending.get(event.call_id||name)||[];queue.push(step);pending.set(event.call_id||name,queue);
    } else if(event.type==='started')Object.assign(step,{title:'开始分析',label:'已开始'});
    else if(event.type==='finished')Object.assign(step,{title:'分析结束',label:runStates[event.status]||'状态未记录',state:event.status||'unknown',end:event.at});
    else if(event.type==='memory_started')Object.assign(step,{title:'整理会话记忆',label:'正在整理'});
    else if(event.type==='memory_finished')Object.assign(step,{title:'会话记忆',label:event.message||event.status,end:event.at});
    else if(event.type==='tool_skipped')Object.assign(step,{title:toolNames[name]||name,label:'预算已用完，未执行',end:event.at});
    else if(event.type==='round_started')Object.assign(step,{title:`第 ${event.round_id} 轮`,label:'正在请求模型'});
    else if(event.type==='round_finished')Object.assign(step,{title:`第 ${event.round_id} 轮结束`,label:event.status==='awaiting_confirmation'?'等待确认':'已返回',end:event.at});
    else Object.assign(step,{title:'其他记录',label:event.type||'事件类型未记录'});
    steps.push(step);
  }
  return steps;
}
