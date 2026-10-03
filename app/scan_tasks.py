"""Durable inventory scan lifecycle; SQLite is the sole task-state authority.

work() performs collection/snapshot persistence and returns the collected data.
It runs outside this module's database transaction. A crash after snapshot commit
but before task completion remains interrupted, never guessed successful.
"""
from datetime import datetime, timezone
import json
import threading
import uuid

LOCK = threading.Lock()
ACTIVE_STATES = {'queued', 'running'}


def _now():
    return datetime.now(timezone.utc).isoformat()


def initialize(connection):
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS scan_tasks (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        for rid, raw in db.execute('SELECT id,payload FROM scan_tasks').fetchall():
            task = json.loads(raw)
            if task['status'] in ACTIVE_STATES:
                stamp = _now()
                task.update(status='interrupted', error='服务已重启，上次清单检查未完成',
                            updated_at=stamp, finished_at=stamp)
                db.execute('UPDATE scan_tasks SET payload=? WHERE id=?', (json.dumps(task, ensure_ascii=False), rid))


def _update(connection, rid, **fields):
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT payload FROM scan_tasks WHERE id=?', (rid,)).fetchone()
        task = json.loads(row[0])
        task.update(fields, updated_at=_now())
        db.execute('UPDATE scan_tasks SET payload=? WHERE id=?', (json.dumps(task, ensure_ascii=False), rid))


def _run(connection, rid, work):
    try:
        _update(connection, rid, status='running', started_at=_now())
        data = work()
        sources = data.get('sources', [])
        issues = data.get('issues', [])
        partial = bool(issues) or any(source.get('status') != 'success' for source in sources)
        # Do not copy arbitrary collector metadata or exception text into task logs.
        summary = [{'id': str(source.get('id', ''))[:200],
                    'status': source.get('status') if source.get('status') in ('success', 'partial', 'failed', 'unchecked') else 'unchecked'}
                   for source in sources]
        _update(connection, rid, status='partial' if partial else 'succeeded',
                sources=summary, issue_count=len(issues), object_count=len(data.get('objects', [])),
                error=None, finished_at=_now())
    except Exception:
        _update(connection, rid, status='failed', error='清单检查失败，请重试；上次成功快照仍保留', finished_at=_now())


def start(connection, work):
    """Return True only when a new worker was registered; False while one exists."""
    with LOCK:
        with connection() as db:
            db.execute('BEGIN IMMEDIATE')
            for row in db.execute('SELECT payload FROM scan_tasks'):
                if json.loads(row[0])['status'] in ACTIVE_STATES:
                    return False
            stamp = _now()
            task = {'id': uuid.uuid4().hex, 'status': 'queued', 'error': None,
                    'created_at': stamp, 'updated_at': stamp, 'started_at': None,
                    'finished_at': None, 'sources': [], 'issue_count': 0, 'object_count': 0}
            db.execute('INSERT INTO scan_tasks VALUES (?,?)', (task['id'], json.dumps(task, ensure_ascii=False)))
        try:
            threading.Thread(target=_run, args=(connection, task['id'], work), daemon=True).start()
        except Exception:
            _update(connection, task['id'], status='failed', error='无法启动清单检查，请重试', finished_at=_now())
            return False
    return True


def list_tasks(connection):
    with connection() as db:
        return [json.loads(row[0]) for row in db.execute('SELECT payload FROM scan_tasks ORDER BY rowid DESC LIMIT 20')]


def status(connection):
    tasks = list_tasks(connection)
    task = next((task for task in tasks if task['status'] in ACTIVE_STATES), tasks[0] if tasks else None)
    return {'running': bool(task and task['status'] in ACTIVE_STATES),
            'error': task.get('error') if task else None, 'task': task}
