"""Read one directory level; cursors refer to bounded, process-local snapshots."""
from collections import OrderedDict
import os
from pathlib import Path
import secrets
import threading
import time

import psutil

PAGE_SIZE = 150
SNAPSHOT_TTL = 120
MAX_SNAPSHOTS = 16
_snapshots = OrderedDict()
_lock = threading.Lock()


def _expired():
    return {'error': '目录分页已过期，请刷新后重试', 'code': 'cursor_expired'}, 409


def _prune():
    now = time.monotonic()
    for key in list(_snapshots):
        if now - _snapshots[key]['created'] >= SNAPSHOT_TTL:
            del _snapshots[key]


def _page(snapshot, offset):
    entries = snapshot['matches']
    next_offset = offset + PAGE_SIZE
    return {**snapshot['metadata'], 'entries': entries[offset:next_offset],
            'next': snapshot['cursors'].get(next_offset)}, 200


def browse_directory(body):
    raw = body.get('path', '')
    if not isinstance(raw, str) or not raw:
        return {'error': '请选择一个磁盘或目录'}, 400
    path = Path(raw)
    if not path.is_absolute() or raw.startswith(('\\\\', '//')):
        return {'error': '仅支持本机磁盘目录'}, 400
    query = str(body.get('query', '')).casefold()
    mode = body.get('mode', '全部')
    if mode not in ('全部', '文件夹', '文件'):
        return {'error': '目录分类无效'}, 400
    cursor = body.get('cursor')
    identity = (os.path.normcase(os.path.abspath(raw)), query, mode)
    if cursor is not None:
        if not isinstance(cursor, str) or not cursor.isascii() or len(cursor) != 43:
            return _expired()
        with _lock:
            _prune()
            for snapshot in _snapshots.values():
                if snapshot['identity'] == identity:
                    for offset, token in snapshot['cursors'].items():
                        if secrets.compare_digest(token, cursor):
                            return _page(snapshot, offset)
        return _expired()
    # Numeric offsets cannot identify a stable enumeration.
    if body.get('offset', 0) not in (0, '0', None):
        return _expired()
    try:
        # Reject links in every component before resolving, including junctions.
        for component in (path, *path.parents):
            if component.is_symlink() or component.is_junction():
                return {'error': '不自动跟随链接目录，请选择实际目录'}, 403
        path = path.resolve(strict=True)
        roots = [Path(p.mountpoint).resolve() for p in psutil.disk_partitions()
                 if 'cdrom' not in p.opts and not p.mountpoint.startswith(('\\\\', '//'))]
        if not any(path.is_relative_to(root) for root in roots):
            return {'error': '路径不在本机磁盘中'}, 403
        entries = []
        with os.scandir(path) as iterator:
            for entry in iterator:
                if len(entries) >= 20000:
                    return {'error': '此目录超过 20,000 项，请使用文件资源管理器查看'}, 422
                try:
                    entries.append({'name': entry.name, 'path': entry.path,
                                    'directory': entry.is_dir(follow_symlinks=False),
                                    'link': entry.is_symlink() or Path(entry.path).is_junction()})
                except OSError:
                    continue
        entries.sort(key=lambda e: (not e['directory'], e['name'].casefold(), e['name']))
        matches = [e for e in entries if query in e['name'].casefold() and
                   (mode == '全部' or (mode == '文件夹' and e['directory']) or
                    (mode == '文件' and not e['directory']))]
        snapshot = {'identity': identity, 'created': time.monotonic(), 'matches': matches,
                    'cursors': {i: secrets.token_urlsafe(32) for i in range(PAGE_SIZE, len(matches), PAGE_SIZE)},
                    'metadata': {'path': str(path), 'parent': str(path.parent) if path.parent != path else None,
                                 'total': len(matches), 'directoryCount': sum(e['directory'] for e in entries),
                                 'fileCount': sum(not e['directory'] for e in entries)}}
        with _lock:
            _prune()
            _snapshots[secrets.token_urlsafe(24)] = snapshot
            while len(_snapshots) > MAX_SNAPSHOTS:
                _snapshots.popitem(last=False)
        return _page(snapshot, 0)
    except PermissionError:
        return {'error': '没有权限读取此目录，可返回上级选择其他位置'}, 403
    except FileNotFoundError:
        return {'error': '目录不存在，或磁盘已断开'}, 404
    except (OSError, ValueError):
        return {'error': '无法读取此位置，请返回上级重试'}, 400
