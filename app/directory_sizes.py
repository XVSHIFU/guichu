"""On-demand metadata-only size jobs; SQLite is authoritative across restarts.

Bytes count logical file lengths, deduplicated by (device, inode), not allocated
disk space. Directory contents can change while walking: even a successful job
is an observation during the scan, not a filesystem snapshot. No links followed.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import threading
import time
import uuid

import psutil

MAX_SECONDS = 120
MAX_ENTRIES = 200000
PROGRESS_INTERVAL = 0.5
ACTIVE = {}
LOCK = threading.RLock()
TERMINAL = {'succeeded', 'partial', 'cancelled', 'interrupted', 'failed'}


def is_running():
    with LOCK:
        return bool(ACTIVE)


def _now():
    return datetime.now(timezone.utc).isoformat()


def initialize(connection):
    with connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS directory_size_tasks (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL)')
        for rid, raw in db.execute('SELECT id,payload FROM directory_size_tasks').fetchall():
            task = json.loads(raw)
            if task['status'] not in TERMINAL:
                task.update(status='interrupted', error='服务已重启，统计未完成，可重新开始', updated_at=_now())
                db.execute('UPDATE directory_size_tasks SET payload=? WHERE id=?', (json.dumps(task, ensure_ascii=False), rid))


def _persist(connection, task):
    task['updated_at'] = _now()
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        # Keep a cancellation request persisted by the HTTP thread.
        row = db.execute('SELECT payload FROM directory_size_tasks WHERE id=?', (task['id'],)).fetchone()
        if row and json.loads(row[0]).get('cancel_requested'):
            task['cancel_requested'] = True
        db.execute('UPDATE directory_size_tasks SET payload=? WHERE id=?',
                   (json.dumps(task, ensure_ascii=False), task['id']))


def _linked(path):
    return path.is_symlink() or path.is_junction()


def _validate(raw):
    if not isinstance(raw, str) or not raw or len(raw) > 4096:
        raise ValueError('请选择本机目录')
    path = Path(raw)
    if not path.is_absolute() or raw.startswith(('\\\\', '//')):
        raise ValueError('仅支持本机磁盘绝对目录')
    if any(_linked(component) for component in (path, *path.parents)):
        raise ValueError('不跟随链接目录')
    path = path.resolve(strict=True)
    if not stat.S_ISDIR(path.stat().st_mode):
        raise ValueError('请选择普通目录')
    roots = [Path(part.mountpoint).resolve() for part in psutil.disk_partitions()
             if 'cdrom' not in part.opts and not part.mountpoint.startswith(('\\\\', '//'))]
    if not any(path.is_relative_to(root) for root in roots):
        raise ValueError('目录不在本机磁盘中')
    return path


def _worker(connection, task, cancel):
    last_update = 0.0
    deadline = time.monotonic() + MAX_SECONDS
    stack = [Path(task['path'])]
    seen = set()
    def progress(force=False):
        nonlocal last_update
        current = time.monotonic()
        if force or current - last_update >= PROGRESS_INTERVAL:
            _persist(connection, task)
            last_update = current
    def stopped():
        if cancel.is_set():
            task['cancel_requested'] = True
            return True
        if time.monotonic() >= deadline:
            task['limit'] = 'time'
            return True
        return False
    try:
        task['status'] = 'running'
        progress(True)
        while stack and not stopped():
            directory = stack.pop()
            try:
                # Recheck queued directory components; never deliberately traverse
                # a link introduced after enumeration. A mutable filesystem is
                # still not an atomic snapshot.
                if any(_linked(part) for part in (directory, *directory.parents)):
                    task['skipped'] += 1
                    progress()
                    continue
                with os.scandir(directory) as entries:
                    task['directories'] += 1
                    for entry in entries:
                        if stopped():
                            break
                        if task['entries'] >= MAX_ENTRIES:
                            task['limit'] = 'entries'
                            break
                        task['entries'] += 1
                        try:
                            if entry.is_symlink() or Path(entry.path).is_junction():
                                task['skipped'] += 1
                            elif entry.is_dir(follow_symlinks=False):
                                stack.append(Path(entry.path))
                            else:
                                # Windows DirEntry.stat may leave st_ino/st_dev
                                # zero; os.stat supplies stable hardlink identity.
                                metadata = os.stat(entry.path, follow_symlinks=False)
                                if not stat.S_ISREG(metadata.st_mode):
                                    task['skipped'] += 1
                                else:
                                    # A zero inode is not a reliable deduplication
                                    # identity; use the distinct entry path instead.
                                    identity = (metadata.st_dev, metadata.st_ino) if metadata.st_ino else entry.path
                                    if identity in seen:
                                        task['hardlinks'] += 1
                                    else:
                                        seen.add(identity)
                                        task['files'] += 1
                                        task['bytes'] += metadata.st_size
                        except OSError:
                            task['errors'] += 1
                        progress()
                    if cancel.is_set() or task['limit']:
                        break
            except OSError:
                task['errors'] += 1
                progress()
        task['status'] = ('cancelled' if cancel.is_set() else
                          'partial' if task['errors'] or task['skipped'] or task['limit'] else 'succeeded')
    except Exception:
        task.update(status='cancelled' if cancel.is_set() else 'failed', error='统计未完成，请重新尝试')
    finally:
        try:
            progress(True)
        finally:
            with LOCK:
                ACTIVE.pop(task['id'], None)


def dispatch(connection, route, body):
    if not isinstance(body, dict):
        return {'error': '无效请求'}, 400
    action = route.removeprefix('/api/size/')
    if action not in {'start', 'get', 'cancel', 'list'}:
        return {'error': '接口不存在'}, 404
    if action == 'list':
        with connection() as db:
            tasks = [json.loads(row[0]) for row in db.execute('SELECT payload FROM directory_size_tasks')]
        return {'tasks': sorted(tasks, key=lambda item: item['created_at'], reverse=True)[:100]}, 200
    if action in {'get', 'cancel'}:
        rid = body.get('id')
        if not isinstance(rid, str):
            return {'error': '任务不存在'}, 404
        with LOCK:
            with connection() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT payload FROM directory_size_tasks WHERE id=?', (rid,)).fetchone()
                if row is None:
                    return {'error': '任务不存在'}, 404
                task = json.loads(row[0])
                if action == 'cancel' and task['status'] not in TERMINAL:
                    signal = ACTIVE.get(rid)
                    if signal:
                        signal.set()
                    task.update(cancel_requested=True, updated_at=_now())
                    db.execute('UPDATE directory_size_tasks SET payload=? WHERE id=?', (json.dumps(task, ensure_ascii=False), rid))
            return {'task': task}, 200
    request_id, raw = body.get('request_id'), body.get('path')
    if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 128:
        return {'error': '请求标识无效'}, 400
    if not isinstance(raw, str) or not raw or len(raw) > 4096:
        return {'error': '请选择本机目录'}, 400
    requested_path = os.path.normcase(os.path.abspath(raw))
    with LOCK:
        with connection() as db:
            prior = db.execute('SELECT payload FROM directory_size_tasks WHERE request_id=?', (request_id,)).fetchone()
            if prior:
                task = json.loads(prior[0])
                if task['requested_path'] != requested_path:
                    return {'error': '请求标识已用于其他目录'}, 409
                return {'task': task}, 200
        if ACTIVE:
            return {'error': '已有目录统计正在运行，请等待完成或取消'}, 409
        try:
            path = _validate(raw)
        except (ValueError, OSError):
            return {'error': '目录不可用；请选择本机磁盘中的普通目录，不支持链接或网络目录'}, 400
        stamp = _now()
        task = {'id': uuid.uuid4().hex, 'request_id': request_id, 'requested_path': requested_path,
                'path': str(path), 'status': 'queued', 'bytes': 0, 'files': 0, 'directories': 0,
                'errors': 0, 'skipped': 0, 'entries': 0, 'hardlinks': 0, 'limit': None, 'error': None,
                'cancel_requested': False, 'created_at': stamp, 'updated_at': stamp}
        with connection() as db:
            db.execute('INSERT INTO directory_size_tasks VALUES (?,?,?)',
                       (task['id'], request_id, json.dumps(task, ensure_ascii=False)))
        cancel = threading.Event()
        ACTIVE[task['id']] = cancel
        threading.Thread(target=_worker, args=(connection, dict(task), cancel), daemon=True).start()
        return {'task': task}, 202
