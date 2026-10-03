"""Atomic, versioned batch classifications of workbench software metadata."""
import json
import uuid
from datetime import datetime, timezone

CATEGORIES={'办公与协作','游戏与平台','开发工具','开发环境','网络与远程','影音与创作','系统与驱动','其他软件'}

def initialize(connection):
    with connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS categories(object_id TEXT PRIMARY KEY,value TEXT NOT NULL,updated TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS category_actions(id TEXT PRIMARY KEY,request_id TEXT UNIQUE NOT NULL,request_payload TEXT NOT NULL,payload TEXT NOT NULL)')

def _now():return datetime.now(timezone.utc).isoformat()
def _json(v):return json.dumps(v,ensure_ascii=False,sort_keys=True)
def _read(db,ids):
    return {i:list(row) if (row:=db.execute('SELECT value,updated FROM categories WHERE object_id=?',(i,)).fetchone()) else None for i in ids}

def dispatch(connection,operation,body,objects):
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        if operation=='list':return {'actions':[json.loads(r[0]) for r in db.execute('SELECT payload FROM category_actions ORDER BY rowid DESC')]},200
        if operation=='propose':
            changes=body.get('changes')
            if not isinstance(changes,list) or not 1<=len(changes)<=50:return {'error':'每批须有 1–50 个分类变更'},400
            ids=[];selected=[]
            for change in changes:
                if not isinstance(change,dict) or set(change)!={'object_id','category'} or not isinstance(change['object_id'],str) or (change['category'] is not None and (not isinstance(change['category'],str) or change['category'] not in CATEGORIES)):
                    return {'error':'分类参数无效'},400
                obj=next((o for o in objects if o['id']==change['object_id'] and o['kind']=='software'),None)
                if not obj or obj['id'] in ids:return {'error':'软件不存在或同批重复'},400
                ids.append(obj['id']);selected.append({'id':obj['id'],'name':obj['name'],'category':change['category']})
            request=body.get('request_id')
            if not isinstance(request,str) or not request or len(request)>128:return {'error':'请求标识无效'},400
            prior=db.execute('SELECT request_payload,payload FROM category_actions WHERE request_id=?',(request,)).fetchone()
            if prior:return ({'action':json.loads(prior[1])},200) if prior[0]==_json(changes) else ({'error':'请求标识重复'},409)
            before=_read(db,ids)
            after={c['object_id']:[c['category'],None] if c['category'] is not None else None for c in changes}
            action={'id':uuid.uuid4().hex,'revision':1,'object':{'id':ids[0],'name':f'{len(ids)} 个软件','kind':'software'},'targets':selected,'before':before,'after':after,'state':'pending','created_at':_now()}
            db.execute('INSERT INTO category_actions VALUES(?,?,?,?)',(action['id'],request,_json(changes),_json(action)))
            return {'action':action},200
        row=db.execute('SELECT payload FROM category_actions WHERE id=?',(body.get('id'),)).fetchone()
        if not row:return {'error':'提案不存在'},404
        action=json.loads(row[0])
        if type(body.get('revision')) is not int or body['revision']!=action['revision']:return {'error':'版本已变化'},409
        if operation not in {'confirm','restore'}:return {'error':'操作不存在'},404
        restore=operation=='restore';success='restored' if restore else 'applied'
        if action['state']==success:return {'action':action},200
        if action['state']!=('applied' if restore else 'pending'):return {'error':'提案当前不可执行','action':action},409
        expected=action['after'] if restore else action['before']
        existing={o['id'] for o in objects if o['kind']=='software'}
        if _read(db,list(expected))!=expected or (not restore and not set(expected)<=existing):
            action.update(state='restore_conflict' if restore else 'conflict',error='分类或清单在预览后发生变化；本批未修改任何对象')
            db.execute('UPDATE category_actions SET payload=? WHERE id=?',(_json(action),action['id']))
            return {'error':action['error'],'action':action},409
        target=action['before'] if restore else action['after']
        for oid,value in target.items():
            if value is None:db.execute('DELETE FROM categories WHERE object_id=?',(oid,))
            else:
                if not restore:value[1]=_now()
                db.execute('INSERT INTO categories VALUES(?,?,?) ON CONFLICT(object_id) DO UPDATE SET value=excluded.value,updated=excluded.updated',(oid,*value))
        if _read(db,list(target))!=target:raise RuntimeError('分类写后验证失败')
        action.update(state=success,updated_at=_now())
        db.execute('UPDATE category_actions SET payload=? WHERE id=?',(_json(action),action['id']))
        return {'action':action},200
