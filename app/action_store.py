"""Versioned proposals that only change the workbench's notes table."""
import hashlib
import json
import uuid
from datetime import datetime, timezone
import action_origin


DECISIONS = {'未标记', '保留', '待确认'}


def initialize(connection):
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS action_meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL)')
        row = db.execute("SELECT value FROM action_meta WHERE key='schema_version'").fetchone()
        version = row[0] if row else 0
        if type(version) is not int or not 0 <= version <= 1:
            raise RuntimeError('不支持的动作数据库版本')
        if version < 1:
            db.execute('CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, request_payload TEXT NOT NULL, payload TEXT NOT NULL)')
        db.execute("INSERT INTO action_meta VALUES ('schema_version', 1) ON CONFLICT(key) DO UPDATE SET value=excluded.value")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _digest(note):
    return hashlib.sha256(_json(note).encode()).hexdigest()


def _note(db, object_id):
    row = db.execute('SELECT id,decision,body,updated FROM notes WHERE id=?', (object_id,)).fetchone()
    return dict(zip(('id', 'decision', 'body', 'updated'), row)) if row else None


def _save(db, action):
    action['updated_at'] = _now()
    db.execute('UPDATE actions SET payload=? WHERE id=?', (_json(action), action['id']))


def _write_note(db, note):
    db.execute('INSERT INTO notes (id,decision,body,updated) VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET decision=excluded.decision,body=excluded.body,updated=excluded.updated',
               (note['id'], note['decision'], note['body'], note['updated']))


def dispatch(connection, route, body, objects):
    action_name = route.removeprefix('/api/action/')
    if action_name not in {'propose', 'list', 'confirm', 'restore'}:
        return {'error': '动作接口不存在'}, 404
    if not isinstance(body, dict):
        return {'error': '无效请求'}, 400
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        if action_name == 'list':
            actions = [json.loads(row[0]) for row in db.execute('SELECT payload FROM actions')]
            actions.sort(key=lambda action: action['created_at'], reverse=True)
            return {'actions': actions}, 200
        if action_name == 'propose':
            object_id, decision, request_id = (body.get(k) for k in ('object_id', 'decision', 'request_id'))
            if not isinstance(object_id, str) or not object_id or len(object_id) > 256:
                return {'error': '对象 ID 格式无效'}, 400
            if not isinstance(decision, str) or decision not in DECISIONS:
                return {'error': '保留决定无效'}, 400
            if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 128:
                return {'error': '请求 ID 格式无效'}, 400
            request_data = {'object_id': object_id, 'decision': decision}
            try:
                origin = action_origin.normalize(body.get('origin'))
            except action_origin.OriginError as exc:
                return {'error': str(exc)}, exc.status
            if origin is not None:
                request_data['origin'] = origin
            request_payload = _json(request_data)
            previous = db.execute('SELECT request_payload,payload FROM actions WHERE request_id=?', (request_id,)).fetchone()
            if previous:
                if previous[0] != request_payload:
                    return {'error': '请求 ID 已用于其他内容'}, 409
                return {'action': json.loads(previous[1])}, 200
            obj = next((o for o in objects if o.get('id') == object_id), None)
            if obj is None:
                return {'error': '对象不在当前清单中，请刷新后重新选择'}, 404
            try:
                origin_snapshot = action_origin.resolve(db, origin, object_id)
            except action_origin.OriginError as exc:
                return {'error': str(exc)}, exc.status
            before = _note(db, object_id)
            timestamp = _now()
            action = dict(id=uuid.uuid4().hex, revision=1,
                          object={k: obj.get(k, '') for k in ('id', 'name', 'kind', 'path', 'source')},
                          before=before, after=dict(id=object_id, decision=decision, body=before['body'] if before else '', updated=None),
                          base_digest=_digest(before), state='pending', created_at=timestamp, updated_at=timestamp)
            if origin_snapshot is not None:
                action['origin'] = origin_snapshot
            db.execute('INSERT INTO actions VALUES (?,?,?,?)', (action['id'], request_id, request_payload, _json(action)))
            return {'action': action}, 200
        action_id = body.get('id')
        if not isinstance(action_id, str) or not action_id:
            return {'error': '动作不存在'}, 404
        row = db.execute('SELECT payload FROM actions WHERE id=?', (action_id,)).fetchone()
        if not row:
            return {'error': '动作不存在'}, 404
        action = json.loads(row[0])
        if type(body.get('revision')) is not int or body['revision'] != action['revision']:
            return {'error': '动作版本已变化，请重新核对', 'action': action}, 409
        object_id = action['object']['id']
        current = _note(db, object_id)
        if action_name == 'confirm':
            if action['state'] == 'applied':
                return {'action': action}, 200
            if action['state'] != 'pending':
                return {'error': '此动作已结束，请重新创建提案', 'action': action}, 409
            if not any(o.get('id') == object_id for o in objects):
                action.update(state='conflict', error='对象已不在当前清单中，未写入任何决定')
                _save(db, action)
                return {'error': action['error'], 'action': action}, 409
            if _digest(current) != action['base_digest']:
                action.update(state='conflict', error='备注或保留决定在预览后发生变化，未覆盖新内容')
                _save(db, action)
                return {'error': action['error'], 'action': action}, 409
            action['after']['updated'] = _now()
            _write_note(db, action['after'])
            action['state'] = 'applied'
        else:
            if action['state'] == 'restored':
                return {'action': action}, 200
            if action['state'] != 'applied':
                return {'error': '此动作当前不能恢复', 'action': action}, 409
            if _digest(current) != _digest(action['after']):
                action.update(state='restore_conflict', error='动作执行后备注已变化，恢复不会覆盖新内容')
                _save(db, action)
                return {'error': action['error'], 'action': action}, 409
            # Restoring internal metadata remains possible after inventory removal.
            if action['before'] is None:
                db.execute('DELETE FROM notes WHERE id=?', (object_id,))
            else:
                _write_note(db, action['before'])
            action['state'] = 'restored'
        _save(db, action)
        return {'action': action}, 200
