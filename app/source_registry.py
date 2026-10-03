"""Explicit user registrations of local portable-tool and project directories."""
import os
import ctypes
from pathlib import Path
import uuid
from datetime import datetime, timezone

TYPES = {'portable', 'project'}
MAX_SOURCES = 20


def initialize(connection):
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS registered_sources (id TEXT PRIMARY KEY, type TEXT NOT NULL, path TEXT NOT NULL, normalized_path TEXT NOT NULL, label TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(type,normalized_path))')


def _row(row):
    return dict(zip(('id', 'type', 'path', 'label', 'created_at'), row))


def list_sources(connection):
    with connection() as db:
        return [_row(row) for row in db.execute('SELECT id,type,path,label,created_at FROM registered_sources ORDER BY created_at,id')]


def _directory(value):
    if not isinstance(value, str) or not value or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise ValueError('请输入有效目录路径')
    path = Path(value)
    if value.startswith(('\\\\', '//')) or not path.is_absolute():
        raise ValueError('仅支持本机绝对目录路径')
    if os.name == 'nt':
        get_drive_type = ctypes.WinDLL('kernel32', use_last_error=True).GetDriveTypeW
        get_drive_type.argtypes = [ctypes.c_wchar_p]
        get_drive_type.restype = ctypes.c_uint
        if get_drive_type(path.anchor) not in {2, 3, 5, 6}:
            raise ValueError('不支持网络映射磁盘或不可用磁盘')
    # Check lexical ancestors before normalization so link/.. cannot hide a link.
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('目录及其上级不能使用符号链接或目录联接')
    path = path.resolve(strict=True)
    if path == Path(path.anchor):
        raise ValueError('不能登记整个磁盘根目录，请选择具体目录')
    if not path.is_dir():
        raise ValueError('请选择已存在的普通目录')
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('目录及其上级不能使用符号链接或目录联接')
    return str(path), os.path.normcase(os.path.normpath(str(path)))


def dispatch(connection, route, body):
    command = route.removeprefix('/api/source/')
    allowed = {'list': set(), 'add': {'type', 'path', 'label'}, 'remove': {'id'}}
    if command not in allowed:
        return {'error': '来源接口不存在'}, 404
    if not isinstance(body, dict) or set(body) - allowed[command]:
        return {'error': '来源登记请求格式无效'}, 400
    if command == 'list':
        return {'sources': list_sources(connection)}, 200
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        if command == 'remove':
            source_id = body.get('id')
            if not isinstance(source_id, str) or not source_id:
                return {'error': '来源登记不存在'}, 404
            result = db.execute('DELETE FROM registered_sources WHERE id=?', (source_id,))
            return ({'ok': True}, 200) if result.rowcount == 1 else ({'error': '来源登记不存在'}, 404)
        source_type, label = body.get('type'), body.get('label', '')
        if not isinstance(source_type, str) or source_type not in TYPES:
            return {'error': '来源类型须为 portable 或 project'}, 400
        if not isinstance(label, str) or len(label) > 80 or any(ord(c) < 32 for c in label):
            return {'error': '来源名称须不超过 80 字且不含控制字符'}, 400
        try:
            path, normalized = _directory(body.get('path'))
        except (ValueError, OSError, RuntimeError):
            return {'error': '请选择已存在的本机普通目录；不支持磁盘根、网络路径或带链接的目录'}, 400
        existing = db.execute('SELECT id,type,path,label,created_at FROM registered_sources WHERE type=? AND normalized_path=?', (source_type, normalized)).fetchone()
        if existing:
            return {'source': _row(existing)}, 200
        if db.execute('SELECT COUNT(*) FROM registered_sources').fetchone()[0] >= MAX_SOURCES:
            return {'error': '最多登记 20 个来源，请先移除不再需要的登记'}, 409
        source = dict(id=uuid.uuid4().hex, type=source_type, path=path, label=label.strip() or Path(path).name[:80],
                      created_at=datetime.now(timezone.utc).isoformat(timespec='microseconds'))
        db.execute('INSERT INTO registered_sources VALUES (?,?,?,?,?,?)', (source['id'], source_type, path, normalized, source['label'], source['created_at']))
        return {'source': source}, 200
