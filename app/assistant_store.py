"""Persist conversations without generating messages or executing proposals."""
import json
import uuid
from datetime import datetime, timezone


def initialize(connection):
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS assistant_meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL)')
        row = db.execute("SELECT value FROM assistant_meta WHERE key='schema_version'").fetchone()
        version = row[0] if row else 0
        if not isinstance(version, int) or not 0 <= version <= 2:
            raise RuntimeError('不支持的助手数据库版本')
        if version < 1:
            db.execute('CREATE TABLE IF NOT EXISTS assistant_sessions (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS assistant_requests (session_id TEXT NOT NULL, request_id TEXT NOT NULL, PRIMARY KEY(session_id, request_id))')
        if version < 2:
            columns = {row[1] for row in db.execute('PRAGMA table_info(assistant_requests)')}
            if 'request_payload' not in columns:
                db.execute('ALTER TABLE assistant_requests ADD COLUMN request_payload TEXT')
        db.execute("INSERT INTO assistant_meta VALUES ('schema_version', 2) ON CONFLICT(key) DO UPDATE SET value=excluded.value")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _id():
    return uuid.uuid4().hex


def _target(value, objects):
    if value is None or value == '':
        return None
    if not isinstance(value, str):
        raise ValueError('目标 ID 格式无效')
    obj = next((o for o in objects if o.get('id') == value), None)
    if obj is None:
        raise ValueError('目标已不在当前清单，请重新选择；历史内容仍保留')
    return {key: obj.get(key, '') for key in ('id', 'name', 'path', 'kind', 'source')}


def _targets(body, objects):
    values = body.get('target_ids') if 'target_ids' in body else ([body['target_id']] if body.get('target_id') else [])
    if not isinstance(values, list) or len(values) > 20 or any(not isinstance(v, str) or not v for v in values):
        raise ValueError('一次最多选择20个有效对象')
    return [_target(value, objects) for value in dict.fromkeys(values)]


def _text(body, key, limit, required=False):
    value = body.get(key, '')
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f'{key} 不能为空或超过 {limit} 字符' if required else f'{key} 格式无效或超过 {limit} 字符')
    return value


def dispatch(connection, route, body, objects):
    """Return a JSON payload and HTTP status using the application's DB factory."""
    action = route.removeprefix('/api/assistant/')
    if action in {'send', 'confirm'}:
        return {'error': '此旧接口已停用，请使用 /api/run/start 发起模型任务'}, 410
    if action not in {'list', 'create', 'get', 'update', 'delete'}:
        return {'error': '接口不存在'}, 404
    if not isinstance(body, dict):
        return {'error': '无效请求'}, 400
    try:
        with connection() as db:
            # Serialize conversation read-modify-write across HTTP threads.
            db.execute('BEGIN IMMEDIATE')
            if action == 'list':
                sessions = [json.loads(row[0]) for row in db.execute('SELECT payload FROM assistant_sessions')]
                sessions.sort(key=lambda s: s['updated_at'], reverse=True)
                return {'sessions': [{**{k: s[k] for k in ('id', 'title', 'updated_at', 'target', 'mode')},
                                      'targets':s.get('targets', [s['target']] if s.get('target') else [])} for s in sessions]}, 200
            if action == 'create':
                targets = _targets(body, objects)
                session = dict(id=_id(), title='新对话', updated_at=_now(), mode='readonly', draft='',
                               target=targets[0] if targets else None, targets=targets, messages=[], active_run_id=None)
            else:
                sid = body.get('id')
                if not isinstance(sid, str) or not sid:
                    return {'error': '对话不存在'}, 404
                row = db.execute('SELECT payload FROM assistant_sessions WHERE id=?', (sid,)).fetchone()
                if row is None:
                    return {'error': '对话不存在'}, 404
                session = json.loads(row[0])
                if action == 'get':
                    return {'session': session}, 200
                if action == 'delete':
                    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='assistant_runs'").fetchone():
                        db.execute('DELETE FROM assistant_events WHERE run_id IN (SELECT id FROM assistant_runs WHERE session_id=?)', (sid,))
                        db.execute('DELETE FROM assistant_runs WHERE session_id=?', (sid,))
                    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_memory'").fetchone():
                        db.execute('DELETE FROM agent_memory WHERE session_id=?', (sid,))
                    db.execute('DELETE FROM assistant_requests WHERE session_id=?', (sid,))
                    db.execute('DELETE FROM assistant_sessions WHERE id=?', (sid,))
                    return {'ok': True}, 200
                if action == 'update':
                    if 'title' in body:
                        session['title'] = _text(body, 'title', 120, True).strip()
                    if 'draft' in body:
                        session['draft'] = _text(body, 'draft', 8000)
                    if 'target_id' in body or 'target_ids' in body:
                        session['targets'] = _targets(body, objects)
                        session['target'] = next(iter(session['targets']), None)
            session['updated_at'] = _now()
            db.execute('INSERT INTO assistant_sessions VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',
                       (session['id'], json.dumps(session, ensure_ascii=False)))
            return {'session': session}, 200
    except ValueError as exc:
        return {'error': str(exc)}, 400
