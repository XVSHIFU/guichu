"""Persistent read-only runs; model output never grants filesystem authority."""
import json
import threading
import time
import uuid
from agent_budget import effective as effective_budget
from agent import context as agent_context, actions as agent_actions, memory as agent_memory
from agent.registry import Registry
from datetime import datetime,timezone

ACTIVE={}
LOCK=threading.Lock()
TERMINAL={'succeeded','failed','cancelled','interrupted','awaiting_confirmation'}

def now():return datetime.now(timezone.utc).isoformat()

def initialize(connection):
    agent_actions.initialize(connection)
    agent_memory.initialize(connection)
    import directory_sizes
    directory_sizes.initialize(connection)
    with connection() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS assistant_runs(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,request_id TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(session_id,request_id));
        CREATE TABLE IF NOT EXISTS assistant_events(run_id TEXT NOT NULL,seq INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(run_id,seq));''')
        for row in db.execute('SELECT id,payload FROM assistant_runs').fetchall():
            item=json.loads(row[1])
            if item['status'] not in TERMINAL:
                item.update(status='interrupted',error='本地服务已重启；任务未自动重放',updated_at=now())
                db.execute('UPDATE assistant_runs SET payload=? WHERE id=?',(json.dumps(item,ensure_ascii=False),row[0]))
                session_row=db.execute('SELECT payload FROM assistant_sessions WHERE id=?',(item['session_id'],)).fetchone()
                if session_row:
                    session=json.loads(session_row[0]);session['active_run_id']=None
                    session['messages'].append({'id':uuid.uuid4().hex,'role':'assistant','text':item['error'],'mode':'readonly','run_id':item['id'],'status':'interrupted'})
                    db.execute('UPDATE assistant_sessions SET payload=? WHERE id=?',(json.dumps(session,ensure_ascii=False),item['session_id']))

def event(connection,rid,kind,**fields):
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        seq=db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM assistant_events WHERE run_id=?',(rid,)).fetchone()[0]
        db.execute('INSERT INTO assistant_events VALUES (?,?,?)',(rid,seq,json.dumps({'seq':seq,'type':kind,'at':now(),**fields},ensure_ascii=False)))

def update(connection,rid,**fields):
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT payload FROM assistant_runs WHERE id=?',(rid,)).fetchone()
        if not row:return
        item=json.loads(row[0]);item.update(**fields,updated_at=now())
        db.execute('UPDATE assistant_runs SET payload=? WHERE id=?',(json.dumps(item,ensure_ascii=False),rid))

def get(connection,rid,after=0):
    with connection() as db:
        row=db.execute('SELECT payload FROM assistant_runs WHERE id=?',(rid,)).fetchone()
        if not row:return {'error':'任务不存在'},404
        records=db.execute('SELECT payload FROM assistant_events WHERE run_id=? AND seq>? ORDER BY seq LIMIT 500',(rid,after)).fetchall()
        return {'run':json.loads(row[0]),'events':[json.loads(r[0]) for r in records]},200

def start(connection,body,inventory,provider,tools_module,action_context=None):
    if body.get('allow_context') is not True:return {'error':'请先确认将所选对象摘要发送到模型服务'},400
    sid=body.get('session_id');text=body.get('text');request_id=body.get('request_id')
    if not all(isinstance(v,str) and v.strip() for v in [sid,text,request_id]) or len(text)>8000 or len(request_id)>128:return {'error':'请求内容无效'},400
    if text.strip().split(maxsplit=1)[0] in {'/help','/changes','/undo','/stop','/new'}:return {'error':'此命令不调用模型，请使用 /api/agent/command'},400
    public=provider.get_public()
    if not public.get('config',{}).get('model'):return {'error':'请先在设置中完成模型连接'},400
    with LOCK:
        with connection() as db:
            db.execute('BEGIN IMMEDIATE')
            existing=db.execute('SELECT payload FROM assistant_runs WHERE session_id=? AND request_id=?',(sid,request_id)).fetchone()
            if existing:
                run=json.loads(existing[0])
                return ({'run':run},200) if run['input']==text else ({'error':'请求标识已用于其他内容'},409)
            if len(ACTIVE)>=2:return {'error':'当前已有两个运行任务，请等待完成或取消'},429
            row=db.execute('SELECT payload FROM assistant_sessions WHERE id=?',(sid,)).fetchone()
            if not row:return {'error':'对话不存在'},404
            session=json.loads(row[0])
            for active in db.execute('SELECT payload FROM assistant_runs WHERE session_id=?',(sid,)):
                if json.loads(active[0])['status'] not in TERMINAL:return {'error':'此对话仍有运行中的任务'},409
            objects=inventory.get('objects',[]);relations=inventory.get('relations',[])
            target=(session.get('target') or {}).get('id')
            target_missing=bool(target and not any(o['id']==target for o in objects))
            if target_missing:
                restorable=any((p:=json.loads(row[0])).get('state')=='applied' and p.get('object',{}).get('id')==target for row in db.execute('SELECT payload FROM agent_proposals WHERE session_id=?',(sid,)))
                if not restorable:return {'error':'历史目标已不存在，请重新选择对象'},409
            allowed={target} if target else {o['id'] for o in objects}
            if target:
                for r in relations:
                    if r['from']==target:allowed.add(r['to'])
                    if r['to']==target:allowed.add(r['from'])
            eligible=[m for m in session['messages'] if m.get('mode')=='readonly' and m.get('role') in ['user','assistant']]
            history=[{'role':m['role'],'content':m['text']} for m in eligible]
            history_trimmed=len(eligible)>12 or sum(len(m['text']) for m in eligible)>18000 or any(len(m['text'])>6000 for m in eligible)
            rid=uuid.uuid4().hex
            run={'target_missing':target_missing,'history_trimmed':history_trimmed,'prompt_version':agent_context.VERSION,'policy_version':agent_context.VERSION,'skill_versions':{},'context_sources':['task','bounded_history','proposal_decisions']+(['selected_object'] if target else []),'id':rid,'session_id':sid,'request_id':request_id,'target':session.get('target'),'allowed_ids':sorted(allowed),'input':text,'status':'queued','answer':'','created_at':now(),'updated_at':now(),'mode':'readonly','usage':{},'error':None}
            db.execute('INSERT INTO assistant_runs VALUES (?,?,?,?)',(rid,sid,request_id,json.dumps(run,ensure_ascii=False)))
            session['messages'].append({'id':uuid.uuid4().hex,'role':'user','text':text,'run_id':rid,'mode':'readonly'})
            session.update(draft='',mode='readonly',active_run_id=rid,updated_at=now(),plan=None,accepted=False)
            if session['title']=='新对话':session['title']=text[:40]
            db.execute('UPDATE assistant_sessions SET payload=? WHERE id=?',(json.dumps(session,ensure_ascii=False),sid))
        cancel=threading.Event();ACTIVE[rid]=cancel
    threading.Thread(target=run_worker,args=(connection,run,objects,relations,provider,tools_module,cancel,history,action_context),daemon=True).start()
    return {'run':run},202

def run_worker(connection,run,objects,relations,provider,tools_module,cancel,history=None,action_context=None):
    rid=run['id'];answer='';intermediate='';calls=0;usage={};proposals=[];round_id=0;skill_versions={}
    try:
        public=provider.get_public();config=public['config'];budget=effective_budget(config);deadline=time.monotonic()+budget['timeout']
        update(connection,rid,model=config.get('model',''),provider_id=public.get('provider_id'),provider_name=public.get('provider_name'))
        update(connection,rid,status='running');event(connection,rid,'started')
        registry=Registry(connection,run,objects,relations,tools_module,action_context,cancel,deadline)
        catalog=[] if agent_context.is_greeting(run['input']) else registry.tools_catalog()
        with connection() as db:
            decisions=[json.loads(row[0]) for row in db.execute('SELECT payload FROM agent_proposals WHERE session_id=? ORDER BY rowid DESC LIMIT 20',(run['session_id'],))]
        decisions=[{'proposal_id':p['id'],'object_id':p['object']['id'],'name':p['object'].get('name'),'operation':p['operation'],'state':p['state']} for p in decisions]
        max_requests=budget['max_requests']
        memory={'history':history,'memory':None,'status':'not_needed','requests':0,'usage':{},'notice':''}
        if not agent_context.is_greeting(run['input']):
            if run.get('history_trimmed'):event(connection,rid,'memory_started',message='正在整理较早会话')
            memory=agent_memory.prepare(connection,run['session_id'],history or [],provider,cancel,deadline,request_budget=max_requests)
            if cancel.is_set():raise InterruptedError()
            if memory['status']!='not_needed':
                event(connection,rid,'memory_finished',status=memory['status'],message=memory['notice'] or '已载入历史摘要')
            max_requests-=memory['requests']
            usage.update({k:v for k,v in memory['usage'].items() if isinstance(v,(int,float))})
        run['memory_notice']=memory['notice']
        update(connection,rid,memory_status=memory['status'],memory_notice=memory['notice'],memory_requests=memory['requests'])
        messages=agent_context.build(run,objects,memory['history'],(action_context or {}).get('preferences'),decisions,memory=memory['memory'])
        max_calls=budget['max_tool_calls']
        update(connection,rid,budget=budget)
        cache={}
        for round_id in range(1,max_requests+1):
            summarizing=round_id==max_requests or calls>=max_calls
            if summarizing:
                messages.append({'role':'system','content':'本次查询预算已结束。不要再调用工具。根据已有工具结果直接回答用户，区分已核实结论、失败或尚未检查的内容；不要声称已完成未执行的检查。'})
            if cancel.is_set():raise InterruptedError()
            if time.monotonic()>deadline:raise TimeoutError()
            event(connection,rid,'round_started',round_id=round_id,model=config.get('model',''))
            messages.append({'role':'system','content':f'本次剩余工具调用 {max_calls-calls} 次，包含当前请求在内剩余模型请求 {max_requests-round_id+1} 轮。优先复用已有证据，最后一轮仅整理结果。'})
            tool_calls=[];segment=''
            for e in provider.stream_completion(messages,[] if summarizing else catalog,cancel,deadline=deadline):
                if cancel.is_set():raise InterruptedError()
                if time.monotonic()>deadline:raise TimeoutError()
                if e['type']=='text':
                    chunk=e.get('text','');segment+=chunk
                    if len(intermediate)+len(segment)>60000:raise ValueError('回答超过长度限制')
                    event(connection,rid,'text',text=chunk,round_id=round_id,channel='intermediate')
                elif e['type']=='tool_call':tool_calls.append(e)
                elif e['type']=='usage':
                    for k,v in e.get('usage',{}).items():
                        if isinstance(v,(int,float)):usage[k]=usage.get(k,0)+v
            if not tool_calls:
                answer=segment
                if not answer.strip():raise ValueError('模型未返回有效内容')
                event(connection,rid,'round_finished',round_id=round_id,status='succeeded')
                break
            if summarizing:
                raise ValueError('模型未遵守结果整理要求，请重试')
            intermediate+=segment
            messages.append({'role':'assistant','content':segment or None,'tool_calls':[{'id':t['id'],'type':'function','function':{'name':t['name'],'arguments':t['arguments']}} for t in tool_calls]})
            for t in tool_calls:
                if cancel.is_set():raise InterruptedError()
                if calls>=max_calls:
                    messages.append({'role':'tool','tool_call_id':t['id'],'content':json.dumps({'error':{'code':'budget_exhausted','message':'此调用未执行：查询预算已用完，请根据已有结果回答并说明未检查内容'}},ensure_ascii=False)})
                    event(connection,rid,'tool_skipped',name=t['name'],round_id=round_id,reason='budget_exhausted')
                    continue
                calls+=1
                call_id=f'{rid}:{round_id}:{calls}'
                try:arguments=json.loads(t['arguments'])
                except (ValueError,TypeError):arguments=None
                event(connection,rid,'tool_started',name=t['name'],round_id=round_id,call_id=call_id,parent_id=None,arguments=agent_context.safe(arguments))
                before=time.monotonic()
                cached=False
                cacheable=t['name'] in {'load_skill','search_objects','get_object','get_relations','read_config_summary'}
                cache_key=(t['name'],json.dumps(arguments,sort_keys=True,ensure_ascii=False))
                try:
                    if cacheable and cache_key in cache:
                        result=cache[cache_key];cached=True
                    else:
                        result={'error':{'code':'not_needed','message':'日常问候不调用本机工具'}} if agent_context.is_greeting(run['input']) else registry.execute(t['name'],arguments,call_id)
                        if cacheable and not result.get('error'):cache[cache_key]=result
                except (InterruptedError,TimeoutError) as exc:
                    event(connection,rid,'tool_finished',name=t['name'],ok=False,round_id=round_id,call_id=call_id,parent_id=None,result={'error':{'code':'cancelled' if isinstance(exc,InterruptedError) else 'timeout'}},elapsed_ms=round((time.monotonic()-before)*1000))
                    raise
                except (ValueError,KeyError,TypeError):result={'error':{'code':'invalid_arguments','message':'工具参数无效或超出本次允许范围'}}
                safe_result=agent_context.safe(result)
                messages.append({'role':'tool','tool_call_id':t['id'],'content':json.dumps(safe_result,ensure_ascii=False)})
                event(connection,rid,'tool_finished',name=t['name'],ok=not bool(result.get('error')),round_id=round_id,call_id=call_id,parent_id=None,result=safe_result,cached=cached,elapsed_ms=round((time.monotonic()-before)*1000))
                if t['name']=='load_skill' and not result.get('error'):
                    skill_versions[result['skill_id']]=result['version']
                if t['name'] in {'propose_change','propose_restore'} and result.get('proposal'):
                    proposals.append(result['proposal']);event(connection,rid,'proposal',proposal=result['proposal'],round_id=round_id,call_id=call_id)
                    break
            event(connection,rid,'round_finished',round_id=round_id,status='awaiting_confirmation' if proposals else 'succeeded')
            if proposals:
                answer='已生成变更预览，请核对提案卡中的目标、差异和恢复范围，再决定是否确认。'
                break
        else:raise ValueError('已达到模型请求上限，请缩小问题范围')
        if cancel.is_set():raise InterruptedError()
        status='awaiting_confirmation' if proposals else 'succeeded';error=None
        event(connection,rid,'final_answer',text=answer,round_id=round_id)
    except InterruptedError:status='cancelled';error='任务已取消'
    except TimeoutError:status='failed';error='任务超时，请缩小问题范围后重试'
    except Exception as exc:
        status='cancelled' if cancel.is_set() or getattr(exc,'code',None)=='cancelled' else 'failed';error='任务已取消' if status=='cancelled' else (str(exc) if isinstance(exc,ValueError) else '模型服务调用失败，请检查连接设置或重试')
    finally:
        with connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT payload FROM assistant_sessions WHERE id=?',(run['session_id'],)).fetchone()
            if row:
                session=json.loads(row[0]);session['messages'].append({'id':uuid.uuid4().hex,'role':'assistant','text':answer or error,'run_id':rid,'mode':'readonly','status':status,'kind':'final_answer','proposals':proposals})
                session.update(updated_at=now(),active_run_id=None)
                db.execute('UPDATE assistant_sessions SET payload=? WHERE id=?',(json.dumps(session,ensure_ascii=False),run['session_id']))
            row=db.execute('SELECT payload FROM assistant_runs WHERE id=?',(rid,)).fetchone()
            completed=json.loads(row[0]);completed.update(status=status,answer=answer,intermediate_answer=intermediate,proposals=proposals,skill_versions=skill_versions,usage=usage,error=error,updated_at=now())
            db.execute('UPDATE assistant_runs SET payload=? WHERE id=?',(json.dumps(completed,ensure_ascii=False),rid))
        event(connection,rid,'finished',status=status,error=error)
        with LOCK:ACTIVE.pop(rid,None)

def cancel_run(connection,rid):
    with LOCK:
        signal=ACTIVE.get(rid)
        if signal:signal.set()
    result,status=get(connection,rid)
    if status!=200:return result,status
    if result['run']['status']=='awaiting_confirmation':
        with LOCK:
            latest,_=get(connection,rid)
            if latest['run']['status']=='awaiting_confirmation':
                for proposal in agent_actions.list_for_run(connection,rid):
                    if proposal['state']=='pending':
                        agent_actions.resolve(connection,{'session_id':proposal['session_id'],'proposal_id':proposal['id'],'revision':proposal['revision']},[],{},reject=True)
                update(connection,rid,status='cancelled',error='待确认提案已取消，未执行修改')
    return {'ok':True,'status':result['run']['status'],'cancellation_requested':bool(signal)},200


def confirm_proposal(connection,body,inventory,provider=None,tools_module=None,action_context=None):
    with LOCK:
        return agent_actions.resolve(connection,body,inventory.get('objects',[]),action_context or {})


def reject_proposal(connection,body,inventory=None,action_context=None):
    with LOCK:
        return agent_actions.resolve(connection,body,(inventory or {}).get('objects',[]),action_context or {},reject=True)


def command(connection,body):
    import assistant_store
    if not isinstance(body,dict) or not isinstance(body.get('text'),str):return {'error':'命令格式无效'},400
    text=body['text'].strip();name=text.split(maxsplit=1)[0] if text else ''
    if name in {'/inspect','/diagnose','/organize'}:return {'command':name,'requires_model':True,'text':text},200
    if name=='/new':return assistant_store.dispatch(connection,'/api/assistant/create',{},[])
    if name in {'/changes','/undo'}:return {'command':name,'navigate':'actions','text':'请选择本会话的操作记录核对。恢复需要重新预览并确认。'},200
    if name=='/stop':
        with connection() as db:
            row=db.execute('SELECT payload FROM assistant_sessions WHERE id=?',(body.get('session_id'),)).fetchone()
        session=json.loads(row[0]) if row else {}
        if session.get('active_run_id'):return cancel_run(connection,session['active_run_id'])
        with connection() as db:rows=db.execute('SELECT id FROM assistant_runs WHERE session_id=? ORDER BY rowid DESC',(body.get('session_id'),)).fetchall()
        for row in rows:
            run,_=get(connection,row[0])
            if run['run']['status']=='awaiting_confirmation':return cancel_run(connection,row[0])
        return {'ok':True,'text':'当前没有运行中的任务或待确认提案。'},200
    if name=='/help':return {'command':name,'text':'可用命令：/inspect 检查对象；/diagnose 诊断连接；/organize 整理清单；/changes 操作记录；/undo 恢复入口；/stop 停止；/new 新会话。修改仅生成提案，确认按钮才会执行。','skills':list(agent_context.SKILLS)},200
    return {'error':'未知命令，请使用 /help 查看支持的命令'},400
