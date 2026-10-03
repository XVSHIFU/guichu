"""Persisted user-confirmed recycle/MSI actions; never replay interrupted work."""
import json
import os
from pathlib import Path
import threading
import uuid
from datetime import datetime, timezone

import msi_action
import recycle_action
import action_origin

_LOCK = threading.RLock()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def initialize(connection):
    with _LOCK, connection() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS cleanup_actions (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, request_payload TEXT NOT NULL, payload TEXT NOT NULL)')
        for row in db.execute('SELECT payload FROM cleanup_actions').fetchall():
            action = json.loads(row[0])
            if action['state'] == 'executing':
                action.update(state='interrupted', error='上次执行中断；不会自动重试，请人工核对实际结果。', updated_at=_now())
                db.execute('UPDATE cleanup_actions SET payload=? WHERE id=?', (_json(action), action['id']))


def _save(connection, action):
    action['updated_at'] = _now()
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('UPDATE cleanup_actions SET payload=? WHERE id=?', (_json(action), action['id']))


def _snapshot(obj):
    keys = ('id', 'name', 'kind', 'path', 'registryHive', 'registryView', 'registryKey', 'windowsInstaller', 'version')
    return {key: obj[key] for key in keys if key in obj}


def _preview(obj, kind, protected_paths):
    if obj.get('retention') == '保留':
        raise ValueError('对象已标记保留，请先修改保留决定')
    if kind == 'recycle':
        if obj.get('kind') != 'directory' or not isinstance(obj.get('path'), str) or not obj['path']:
            raise ValueError('仅支持当前清单中的普通目录')
        return recycle_action.preview(obj['path'], protected_paths)
    if obj.get('kind') != 'software':
        raise ValueError('仅支持当前清单中的 MSI 软件')
    return msi_action.preview(obj)


def dispatch(connection, route, body, objects, protected_paths):
    with _LOCK:
        return _dispatch(connection, route, body, objects, protected_paths)


def _dispatch(connection, route, body, objects, protected_paths):
    command = route.removeprefix('/api/cleanup/')
    allowed = {'list': set(), 'propose': {'object_id', 'kind', 'request_id', 'origin'}, 'confirm': {'id', 'revision', 'acknowledge'}, 'verify': {'id'}}
    if command not in allowed:
        return {'error': '清理动作接口不存在'}, 404
    if not isinstance(body, dict) or set(body) - allowed[command]:
        return {'error': '清理请求格式无效；不接受自定义路径或命令'}, 400
    with connection() as db:
        if command == 'list':
            actions = [json.loads(row[0]) for row in db.execute('SELECT payload FROM cleanup_actions')]
            actions.sort(key=lambda item: item['created_at'], reverse=True)
            return {'actions': actions}, 200
        if command == 'propose':
            db.execute('BEGIN IMMEDIATE')
            object_id, kind, request_id = (body.get(key) for key in ('object_id', 'kind', 'request_id'))
            if not isinstance(object_id, str) or not object_id or not isinstance(kind, str) or kind not in {'recycle', 'uninstall'} or not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 128:
                return {'error': '对象、操作类型或请求 ID 格式无效'}, 400
            request_data = {'object_id': object_id, 'kind': kind}
            try:
                origin = action_origin.normalize(body.get('origin'))
            except action_origin.OriginError as exc:
                return {'error': str(exc)}, exc.status
            if origin is not None:
                request_data['origin'] = origin
            payload = _json(request_data)
            row = db.execute('SELECT request_payload,payload FROM cleanup_actions WHERE request_id=?', (request_id,)).fetchone()
            if row:
                if row[0] != payload:
                    return {'error': '请求 ID 已用于其他操作'}, 409
                return {'action': json.loads(row[1])}, 200
            obj = next((item for item in objects if item.get('id') == object_id), None)
            if obj is None:
                return {'error': '对象不在当前清单中，请重新检查'}, 404
            if obj.get('retention') == '保留':
                return {'error': '对象已标记保留，请先修改保留决定'}, 409
            try:
                origin_snapshot = action_origin.resolve(db, origin, object_id)
            except action_origin.OriginError as exc:
                return {'error': str(exc)}, exc.status
            try:
                summary = _preview(obj, kind, protected_paths)
            except (OSError, ValueError):
                return {'error': '无法安全生成提案：请核对目标类型、占用、保护范围及登记信息'}, 400
            timestamp = _now()
            action = dict(id=uuid.uuid4().hex, revision=1, kind=kind, object=_snapshot(obj), path=obj.get('path', ''),
                          preview=summary, fingerprint=summary['fingerprint'], state='pending', receipt=None,
                          created_at=timestamp, updated_at=timestamp)
            if origin_snapshot is not None:
                action['origin'] = origin_snapshot
            db.execute('INSERT INTO cleanup_actions VALUES (?,?,?,?)', (action['id'], request_id, payload, _json(action)))
            return {'action': action}, 200
        action_id = body.get('id')
        if not isinstance(action_id, str) or not action_id:
            return {'error': '动作不存在'}, 404
        row = db.execute('SELECT payload FROM cleanup_actions WHERE id=?', (action_id,)).fetchone()
        if not row:
            return {'error': '动作不存在'}, 404
        action = json.loads(row[0])
    if command == 'verify':
        if action['state'] not in {'waiting_user', 'still_registered', 'removed', 'failed', 'interrupted', 'recycled'}:
            return {'error': '此动作尚未执行，不能核验结果', 'action': action}, 409
        if action['kind'] == 'uninstall':
            try:
                result = msi_action.verify(action['object'])
            except (OSError, ValueError):
                return {'error': '无法核验原软件登记，请重新扫描并人工确认', 'action': action}, 409
            action.update(state=result['state'], verification=result)
        else:
            try:
                Path(action['path']).stat()
                present = True
            except FileNotFoundError:
                present = False
            except OSError:
                return {'error': '无法读取原目录状态，请人工检查', 'action': action}, 409
            action['verification'] = dict(path_exists=present, message='原目录仍存在，请核对操作结果。' if present else '原路径已不存在；是否可恢复请在 Windows 回收站中核对。')
        _save(connection, action)
        return {'action': action}, 200
    if type(body.get('revision')) is not int or body['revision'] != action['revision']:
        return {'error': '提案版本不匹配，请重新预览', 'action': action}, 409
    if body.get('acknowledge') is not True:
        return {'error': '请先确认操作范围、使用情况及恢复限制', 'action': action}, 400
    if action['state'] in {'recycled', 'waiting_user', 'still_registered', 'removed'}:
        return {'action': action}, 200
    if action['state'] != 'pending':
        return {'error': '此提案已结束或中断，不会重复执行；请先核对实际结果', 'action': action}, 409
    obj = next((item for item in objects if item.get('id') == action['object']['id']), None)
    if obj is None or _snapshot(obj) != action['object']:
        action.update(state='conflict', error='目标已变化或不在清单中，未执行操作')
        _save(connection, action)
        return {'error': action['error'], 'action': action}, 409
    if obj.get('retention') == '保留':
        action.update(state='conflict', error='对象已标记保留，请先修改保留决定并重新生成提案')
        _save(connection, action)
        return {'error': action['error'], 'action': action}, 409
    try:
        summary = _preview(obj, action['kind'], protected_paths)
        if summary['fingerprint'] != action['fingerprint']:
            raise ValueError('目标内容已变化')
    except (OSError, ValueError):
        action.update(state='conflict', error='内容、占用或软件登记在预览后发生变化，未执行操作')
        _save(connection, action)
        return {'error': action['error'], 'action': action}, 409
    action['state'] = 'executing'
    _save(connection, action)
    try:
        receipt = (recycle_action.apply(action['path'], action['fingerprint'], protected_paths) if action['kind'] == 'recycle'
                   else msi_action.apply(action['object'], action['fingerprint']))
    except (OSError, ValueError) as exc:
        partial = getattr(exc, 'receipt', None)
        if isinstance(partial, dict):
            action['receipt'] = dict(state=partial.get('state') if partial.get('state') in {'failed', 'uncertain'} else 'uncertain',
                                     path=action['path'], restore_note=action['preview'].get('restore_note', '请人工核对实际结果，工作台不自动恢复。'))
        action.update(state='failed', error='操作未正常完成；不会自动重试，请核对系统窗口、原目录及回收站')
        _save(connection, action)
        return {'error': action['error'], 'action': action}, 500
    action.update(state='recycled' if action['kind'] == 'recycle' else 'waiting_user', receipt=receipt)
    _save(connection, action)
    return {'action': action}, 200
