"""Journaled, explicit edits to one server-selected Claude Code MCP configuration."""
import json
import hashlib
import os
from pathlib import Path
import threading
import uuid
from datetime import datetime, timezone

import claude_config_action as adapter
import action_origin

_LOCK = threading.RLock()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _path(value):
    return os.path.normcase(os.path.abspath(value))


def initialize(connection):
    with _LOCK, connection() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS claude_action_meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL)')
        row = db.execute("SELECT value FROM claude_action_meta WHERE key='schema_version'").fetchone()
        version = row[0] if row else 0
        if type(version) is not int or not 0 <= version <= 1:
            raise RuntimeError('不支持的 MCP 动作数据库版本')
        if version < 1:
            db.execute('CREATE TABLE IF NOT EXISTS claude_actions (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, request_payload TEXT NOT NULL, payload TEXT NOT NULL)')
        db.execute("INSERT INTO claude_action_meta VALUES ('schema_version',1) ON CONFLICT(key) DO UPDATE SET value=excluded.value")
        for row in db.execute('SELECT payload FROM claude_actions').fetchall():
            action = json.loads(row[0])
            if action['state'] in {'applying', 'restoring'}:
                action.update(state='interrupted', error='上次操作中断，请核对配置及恢复记录；未自动继续写入', updated_at=_now())
                db.execute('UPDATE claude_actions SET payload=? WHERE id=?', (_json(action), action['id']))


def _save(connection, action):
    action['updated_at'] = _now()
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('UPDATE claude_actions SET payload=? WHERE id=?', (_json(action), action['id']))


def _object(objects, object_id, config_path):
    obj = next((o for o in objects if o.get('id') == object_id), None)
    if not obj or obj.get('kind') != 'mcp' or obj.get('scope') != 'claude' or obj.get('source') != '用户配置':
        return None
    value = obj.get('path')
    if not isinstance(value, str) or _path(value) != _path(config_path):
        return None
    if not isinstance(obj.get('name'), str) or not obj['name']:
        return None
    return obj


def dispatch(connection, route, body, objects, config_path, backup_dir):
    # Held across journal commits and adapter calls: another local request cannot
    # enter a gap between applying/receipt/applied transitions for the same file.
    with _LOCK:
        return _dispatch(connection, route, body, objects, Path(config_path), Path(backup_dir))


def _dispatch(connection, route, body, objects, config_path, backup_dir):
    command = route.removeprefix('/api/mcp-action/')
    fields = {'list': set(), 'propose': {'object_id', 'enabled', 'request_id', 'origin'}, 'confirm': {'id', 'revision'}, 'restore': {'id', 'revision'}}
    if command not in fields:
        return {'error': 'MCP 动作接口不存在'}, 404
    if not isinstance(body, dict) or set(body) - fields[command]:
        return {'error': '请求格式无效；配置路径和服务名称由清单确定'}, 400
    with connection() as db:
        if command == 'list':
            actions = [json.loads(row[0]) for row in db.execute('SELECT payload FROM claude_actions')]
            actions.sort(key=lambda a: a['created_at'], reverse=True)
            # Diagnostic hashes only; reading history never resumes a write.
            interrupted = [a for a in actions if a['state'] in {'interrupted', 'failed', 'restore_conflict'} and _path(a['path']) == _path(config_path)]
            if interrupted:
                try:
                    current_hash = hashlib.sha256(adapter._read(config_path)).hexdigest()
                except (OSError, ValueError):
                    current_hash = None
                for action in interrupted:
                    action['observed_state'] = ('unavailable' if current_hash is None else
                                                'matches_before' if current_hash == action['before_hash'] else
                                                'matches_after' if current_hash == action['after_hash'] else 'changed')
            return {'actions': actions}, 200
        if command == 'propose':
            db.execute('BEGIN IMMEDIATE')
            object_id, enabled, request_id = (body.get(k) for k in ('object_id', 'enabled', 'request_id'))
            if not isinstance(object_id, str) or not object_id or len(object_id) > 256 or type(enabled) is not bool or not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 128:
                return {'error': '对象、启用值或请求 ID 格式无效'}, 400
            request_data = {'object_id': object_id, 'enabled': enabled}
            try:
                origin = action_origin.normalize(body.get('origin'))
            except action_origin.OriginError as exc:
                return {'error': str(exc)}, exc.status
            if origin is not None:
                request_data['origin'] = origin
            payload = _json(request_data)
            row = db.execute('SELECT request_payload,payload FROM claude_actions WHERE request_id=?', (request_id,)).fetchone()
            if row:
                if row[0] != payload:
                    return {'error': '请求 ID 已用于其他提案'}, 409
                return {'action': json.loads(row[1])}, 200
            obj = _object(objects, object_id, config_path)
            if obj is None:
                return {'error': '此对象不是当前 Claude Code 用户配置中的独立 MCP'}, 404
            try:
                origin_snapshot = action_origin.resolve(db, origin, object_id)
            except action_origin.OriginError as exc:
                return {'error': str(exc)}, exc.status
            try:
                preview = adapter.preview(config_path, obj['name'], enabled)
            except (ValueError, OSError):
                return {'error': '无法安全预览该独立 MCP 表，请核对配置格式、名称与权限'}, 400
            timestamp = _now()
            action = dict(id=uuid.uuid4().hex, revision=1,
                          object={k: obj.get(k, '') for k in ('id', 'name', 'kind', 'scope', 'source', 'path')},
                          path=str(config_path.absolute()), server_id=obj['name'],
                          before_enabled=preview['before_enabled'], after_enabled=enabled,
                          hash=preview['before_hash'], before_hash=preview['before_hash'], after_hash=preview['after_hash'],
                          backup_location=str(backup_dir.absolute()), receipt=None, state='pending', created_at=timestamp, updated_at=timestamp)
            if origin_snapshot is not None:
                action['origin'] = origin_snapshot
            db.execute('INSERT INTO claude_actions VALUES (?,?,?,?)', (action['id'], request_id, payload, _json(action)))
            return {'action': action}, 200
        action_id = body.get('id')
        if not isinstance(action_id, str) or not action_id:
            return {'error': '动作不存在'}, 404
        row = db.execute('SELECT payload FROM claude_actions WHERE id=?', (action_id,)).fetchone()
        if not row:
            return {'error': '动作不存在'}, 404
        action = json.loads(row[0])
    if type(body.get('revision')) is not int or body['revision'] != action['revision']:
        return {'error': '动作版本不匹配，请重新核对', 'action': action}, 409
    if _path(action['path']) != _path(config_path):
        return {'error': '动作目标与当前固定配置不一致', 'action': action}, 409
    if command == 'confirm':
        if action['state'] == 'applied':
            return {'action': action}, 200
        if action['state'] != 'pending':
            return {'error': '此提案不能继续确认，请核对历史并重新预览', 'action': action}, 409
        obj = _object(objects, action['object']['id'], config_path)
        if obj is None or obj['name'] != action['server_id']:
            action.update(state='conflict', error='目标已变化或不在当前清单中，未写入配置')
            _save(connection, action)
            return {'error': action['error'], 'action': action}, 409
        action['state'] = 'applying'
        _save(connection, action)
        def on_backup(receipt):
            action.update(receipt=receipt, backup_location=receipt['backup_path'])
            _save(connection, action)
        try:
            receipt = adapter.apply(config_path, action['server_id'], action['after_enabled'], action['before_hash'], backup_dir, on_backup=on_backup)
        except (ValueError, OSError) as exc:
            receipt = getattr(exc, 'receipt', None)
            if receipt:
                action.update(receipt=receipt, backup_location=receipt['backup_path'])
            action.update(state='conflict' if isinstance(exc, ValueError) and not action['receipt'] else 'failed',
                          error='配置已变化或不能安全修改；未继续重试，请核对配置及备份记录' if isinstance(exc, ValueError) else '配置操作失败，请核对权限及备份记录')
            _save(connection, action)
            return {'error': action['error'], 'action': action}, 409 if action['state'] == 'conflict' else 500
        action.update(state='applied', receipt=receipt, backup_location=receipt['backup_path'])
    else:
        if action['state'] == 'restored':
            return {'action': action}, 200
        if action['state'] not in {'applied', 'failed', 'interrupted', 'restore_conflict'} or not action.get('receipt'):
            return {'error': '此动作没有可用恢复记录', 'action': action}, 409
        action['state'] = 'restoring'
        _save(connection, action)
        try:
            adapter.restore(config_path, action['receipt'])
        except (ValueError, OSError) as exc:
            action.update(state='restore_conflict' if isinstance(exc, ValueError) else 'failed',
                          error='配置已有后续变化或备份不匹配，未覆盖恢复' if isinstance(exc, ValueError) else '恢复失败，请核对权限及备份记录')
            _save(connection, action)
            return {'error': action['error'], 'action': action}, 409 if isinstance(exc, ValueError) else 500
        action['state'] = 'restored'
    action.pop('error', None)
    _save(connection, action)
    return {'action': action}, 200
