"""Assistant proposals wrap existing journals; model tools can never confirm them."""
import hashlib
import json
import threading
import uuid
from datetime import datetime,timezone
import action_store
import mcp_action_store
import claude_action_store
import category_action_store
from .context import safe

LOCK=threading.RLock()
TABLES={'action':'actions','mcp-action':'mcp_actions','claude-action':'claude_actions','category-action':'category_actions'}
def now():return datetime.now(timezone.utc).isoformat()
def encode(value):return json.dumps(value,ensure_ascii=False)

def initialize(connection):
    action_store.initialize(connection)
    mcp_action_store.initialize(connection)
    claude_action_store.initialize(connection)
    category_action_store.initialize(connection)
    with connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS agent_proposals(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,run_id TEXT NOT NULL,call_id TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(run_id,call_id))')
        for row in db.execute('SELECT id,payload FROM agent_proposals'):
            p=json.loads(row[1])
            if p['state']=='executing':
                p.update(state='interrupted',error='执行回执未完整保存，请在操作历史核对；未自动重放')
                db.execute('UPDATE agent_proposals SET payload=? WHERE id=?',(encode(p),row[0]))

def list_for_run(connection,rid):
    with connection() as db:return [json.loads(r[0]) for r in db.execute('SELECT payload FROM agent_proposals WHERE run_id=? ORDER BY rowid',(rid,))]

def capabilities(obj,context):
    actions=['retention']
    if context.get('config_path') and mcp_action_store._object([obj],obj['id'],context['config_path']):actions.append('mcp_enabled')
    if context.get('claude_config_path') and claude_action_store._object([obj],obj['id'],context['claude_config_path']):actions.append('claude_mcp_remove')
    if obj.get('kind')=='software':actions.append('batch_category')
    return {'object_id':obj['id'],'actions':actions,'categories':sorted(category_action_store.CATEGORIES) if obj.get('kind')=='software' else [],'confirmation_required':True,'limitations':'批量分类只改工作台元数据；Claude 用户 MCP 仅支持移除注册和备份恢复，不假定 enabled 字段。'}

def dispatch_store(connection,family,operation,body,objects,context):
    if family=='action':return action_store.dispatch(connection,'/api/action/'+operation,body,objects)
    if family=='category-action':return category_action_store.dispatch(connection,operation,body,objects)
    if family=='claude-action':return claude_action_store.dispatch(connection,'/api/mcp-action/'+operation,body,objects,context['claude_config_path'],context['backup_dir'])
    return mcp_action_store.dispatch(connection,'/api/mcp-action/'+operation,body,objects,context['config_path'],context['backup_dir'])

def propose(connection,run,args,objects,context,call_id,restore=False):
    with LOCK:
        with connection() as db:
            prior=db.execute('SELECT payload FROM agent_proposals WHERE run_id=? AND call_id=?',(run['id'],call_id)).fetchone()
            if prior:return {'proposal':json.loads(prior[0])}
        obj=next((o for o in objects if o['id']==args.get('object_id')),None)
        if not restore and (not obj or obj['id'] not in run['allowed_ids']):return {'error':{'code':'scope','message':'对象不在当前任务范围内'}}
        if restore:
            with connection() as db:
                row=db.execute('SELECT payload FROM agent_proposals WHERE id=? AND session_id=?',(args.get('proposal_id'),run['session_id'])).fetchone()
                original=json.loads(row[0]) if row else None
            if not original or original['object']['id']!=args.get('object_id') or original['state']!='applied':return {'error':{'code':'not_restorable','message':'找不到本会话可恢复的已执行提案'}}
            obj=original['object']
            family=original['family']
            with connection() as db:action=json.loads(db.execute('SELECT payload FROM '+TABLES[family]+' WHERE id=?',(original['action_id'],)).fetchone()[0])
            if action['state']!='applied':return {'error':{'code':'changed','message':'原操作状态已变化'}}
        else:
            if args.get('action') not in capabilities(obj,context)['actions']:return {'error':{'code':'unsupported','message':'此对象不支持该动作'}}
            family={'retention':'action','mcp_enabled':'mcp-action','claude_mcp_remove':'claude-action','batch_category':'category-action'}[args['action']]
            params=args.get('parameters')
            required={'action':'decision','mcp-action':'enabled','claude-action':'enabled','category-action':'changes'}[family]
            if not isinstance(params,dict) or set(params)!={required}:return {'error':{'code':'invalid_arguments','message':'修改参数无效'}}
            if family=='claude-action' and params['enabled'] is not False:return {'error':{'code':'invalid_arguments','message':'移除注册须明确 enabled=false；恢复使用 propose_restore'}}
            if family=='category-action':
                changes=params['changes']
                if not isinstance(changes,list) or not changes or any(not isinstance(c,dict) or c.get('object_id') not in run['allowed_ids'] for c in changes) or obj['id']!=changes[0].get('object_id'):
                    return {'error':{'code':'scope','message':'批量分类必须全部在任务授权范围，object_id 须为首项'}}
            body={'object_id':obj['id'],'request_id':'agent-'+hashlib.sha256((run['id']+call_id).encode()).hexdigest(),**params}
            response,status=dispatch_store(connection,family,'propose',body,objects,context)
            if status!=200:return {'error':{'code':'proposal_failed','message':response.get('error','预览失败')}}
            action=response['action']
        with connection() as db:
            db.execute('BEGIN IMMEDIATE')
            session_row=db.execute('SELECT payload FROM assistant_sessions WHERE id=?',(run['session_id'],)).fetchone()
            if not session_row:return {'error':{'code':'session_missing','message':'会话已删除'}}
            session=json.loads(session_row[0])
            # Server-owned provenance; no caller-supplied origin or filesystem path.
            origin={'session_id':run['session_id'],'run_id':run['id'],'title':session['title'],'mode':'readonly','object_id':obj['id'],'run_status':'awaiting_confirmation'}
            if not restore:
                action['origin']=origin
                db.execute('UPDATE '+TABLES[family]+' SET payload=? WHERE id=?',(encode(action),action['id']))
            proposal={'id':uuid.uuid4().hex,'revision':1,'family':family,'action_id':action['id'],'session_id':run['session_id'],'run_id':run['id'],
                      'operation':'restore' if restore else 'confirm','state':'pending','object':action['object'],'preview':action,'created_at':now()}
            db.execute('INSERT INTO agent_proposals VALUES (?,?,?,?,?)',(proposal['id'],run['session_id'],run['id'],call_id,encode(proposal)))
        return {'proposal':proposal}

def resolve(connection,body,objects,context,reject=False):
    if not isinstance(body,dict) or not all(isinstance(body.get(k),str) and body[k] for k in ('session_id','proposal_id')) or type(body.get('revision')) is not int:return {'error':'提案参数无效'},400
    with LOCK:
        with connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT payload FROM agent_proposals WHERE id=? AND session_id=?',(body['proposal_id'],body['session_id'])).fetchone()
            if not row:return {'error':'此会话没有该提案'},404
            p=json.loads(row[0])
            if p['revision']!=body['revision']:return {'error':'提案版本已变化'},409
            sr=db.execute('SELECT payload FROM assistant_sessions WHERE id=?',(p['session_id'],)).fetchone()
            rr=db.execute('SELECT payload FROM assistant_runs WHERE id=?',(p['run_id'],)).fetchone()
            if not sr or not rr:return {'error':'来源会话或任务已不存在'},404
            session,run=json.loads(sr[0]),json.loads(rr[0])
            if p['state']!='pending':return {'proposal':p,'session':session,'run':run},200 if p['state'] in {'applied','restored','rejected'} else 409
            if session.get('active_run_id'):return {'error':'请等待当前分析结束再确认'},409
            if run['status'] in {'cancelled','interrupted'}:return {'error':'来源任务已取消或中断，请重新生成预览'},409
            p['state']='rejected' if reject else 'executing'
            db.execute('UPDATE agent_proposals SET payload=? WHERE id=?',(encode(p),p['id']))
        if not reject:
            try:
                result,status=dispatch_store(connection,p['family'],p['operation'],{'id':p['action_id'],'revision':p['preview']['revision']},objects,context)
                p['preview']=result.get('action',p['preview']);p['state']=p['preview'].get('state') if 'action' in result else 'failed'
                if status!=200:p['error']=result.get('error','执行失败')
            except Exception:
                p.update(state='interrupted',error='未取得完整执行回执，请在操作历史核对；不会自动重放')
        p['updated_at']=now()
        labels={'applied':'已执行并保存回执','restored':'已恢复并保存回执','rejected':'已取消提案，未执行','conflict':'目标已变化，未覆盖','restore_conflict':'恢复冲突，未覆盖','interrupted':'执行结果待核对','failed':'执行失败'}
        with connection() as db:
            db.execute('BEGIN IMMEDIATE')
            session=json.loads(db.execute('SELECT payload FROM assistant_sessions WHERE id=?',(p['session_id'],)).fetchone()[0])
            run=json.loads(db.execute('SELECT payload FROM assistant_runs WHERE id=?',(p['run_id'],)).fetchone()[0])
            message={'id':uuid.uuid4().hex,'role':'assistant','mode':'readonly','kind':'action_result','run_id':p['run_id'],'proposal_id':p['id'],
                     'text':p['object'].get('name','对象')+'：'+labels.get(p['state'],p['state'])+'。'+p.get('error',''),'proposals':[p]}
            session['messages'].append(message);session['updated_at']=now()
            db.execute('UPDATE agent_proposals SET payload=? WHERE id=?',(encode(p),p['id']))
            run['proposals']=[json.loads(r[0]) for r in db.execute('SELECT payload FROM agent_proposals WHERE run_id=?',(p['run_id'],))]
            if all(item['state']!='pending' for item in run['proposals']):run['status']='succeeded' if all(item['state'] in {'applied','restored','rejected'} for item in run['proposals']) else 'failed'
            for m in session['messages']:
                if m.get('run_id')==p['run_id'] and m.get('proposals'):m['proposals']=[p if item.get('id')==p['id'] else item for item in m['proposals']]
            db.execute('UPDATE assistant_sessions SET payload=? WHERE id=?',(encode(session),p['session_id']))
            db.execute('UPDATE assistant_runs SET payload=? WHERE id=?',(encode(run),p['run_id']))
            seq=db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM assistant_events WHERE run_id=?',(p['run_id'],)).fetchone()[0]
            db.execute('INSERT INTO assistant_events VALUES (?,?,?)',(p['run_id'],seq,encode({'seq':seq,'type':'action_result','at':now(),'proposal_id':p['id'],'state':p['state'],'text':message['text']})))
        return {'proposal':p,'session':session,'run':run},200 if p['state'] in {'applied','restored','rejected'} else 409
