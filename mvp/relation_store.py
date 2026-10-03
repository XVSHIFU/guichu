"""User-maintained relationships kept separate from scanned facts."""
import copy
import uuid
from datetime import datetime, timezone


def initialize(connection):
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS manual_relations (id TEXT PRIMARY KEY, from_id TEXT NOT NULL, to_id TEXT NOT NULL, label TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(from_id,to_id,label))')


def _row(row, object_ids):
    relation = dict(zip(('id', 'from', 'to', 'label', 'created_at'), row))
    relation.update(manual=True, missing=relation['from'] not in object_ids or relation['to'] not in object_ids)
    return relation


def _list(db, object_ids):
    return [_row(row, object_ids) for row in db.execute('SELECT id,from_id,to_id,label,created_at FROM manual_relations ORDER BY created_at,id')]


def dispatch(connection, route, body, objects):
    command = route.removeprefix('/api/relation/')
    allowed = {'list': set(), 'add': {'from_id', 'to_id', 'label'}, 'remove': {'id'}}
    if command not in allowed:
        return {'error': '关联接口不存在'}, 404
    if not isinstance(body, dict) or set(body) - allowed[command]:
        return {'error': '关联请求格式无效'}, 400
    object_ids = {obj['id'] for obj in objects}
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        if command == 'list':
            return {'relations': _list(db, object_ids)}, 200
        if command == 'remove':
            relation_id = body.get('id')
            if not isinstance(relation_id, str) or not relation_id:
                return {'error': '人工关联不存在'}, 404
            result = db.execute('DELETE FROM manual_relations WHERE id=?', (relation_id,))
            if result.rowcount != 1:
                return {'error': '人工关联不存在；扫描关系不能在此删除'}, 404
            return {'ok': True}, 200
        source, target, label = (body.get(key) for key in ('from_id', 'to_id', 'label'))
        if not isinstance(source, str) or not isinstance(target, str) or not source or not target:
            return {'error': '请选择两个有效对象'}, 400
        if source not in object_ids or target not in object_ids:
            return {'error': '关联对象已不在当前清单中，请刷新后重试'}, 404
        if source == target:
            return {'error': '不能关联对象自身'}, 400
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80 or any(ord(c) < 32 for c in label):
            return {'error': '关联说明须为 1–80 字且不含控制字符'}, 400
        label = label.strip()
        existing = db.execute('SELECT id,from_id,to_id,label,created_at FROM manual_relations WHERE from_id=? AND to_id=? AND label=?', (source, target, label)).fetchone()
        if existing:
            return {'relation': _row(existing, object_ids)}, 200
        relation_id = uuid.uuid4().hex
        at = datetime.now(timezone.utc).isoformat(timespec='microseconds')
        row = (relation_id, source, target, label, at)
        db.execute('INSERT INTO manual_relations (id,from_id,to_id,label,created_at) VALUES (?,?,?,?,?)', row)
        return {'relation': _row(row, object_ids)}, 200


def overlay(data, connection):
    """Return an independent view; manual edges never alter scan snapshots."""
    if data is None:
        return None
    result = copy.deepcopy(data)
    object_ids = {obj['id'] for obj in result.get('objects', [])}
    with connection() as db:
        manual = _list(db, object_ids)
    # Ignore a previous overlay when called repeatedly; scanned edges have no
    # manual marker and remain intact even when a manual edge is identical.
    relations = [edge for edge in result.get('relations', []) if not edge.get('manual')]
    present = {(edge.get('from'), edge.get('to'), edge.get('label')) for edge in relations}
    for relation in manual:
        key = (relation['from'], relation['to'], relation['label'])
        if not relation['missing'] and key not in present:
            relations.append({key: relation[key] for key in ('id', 'from', 'to', 'label', 'manual')})
            present.add(key)
    result['relations'] = relations
    return result
