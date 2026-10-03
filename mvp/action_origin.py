"""Validate conversation provenance without treating it as action authority."""
import json

TERMINAL = {'succeeded', 'failed', 'cancelled', 'interrupted', 'awaiting_confirmation'}
ACTION_TABLES = (('actions', 'action'), ('mcp_actions', 'mcp-action'), ('cleanup_actions', 'cleanup'), ('category_actions','category-action'), ('claude_actions','claude-action'))


class OriginError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def normalize(origin):
    """Stable request identity, independent of mutable titles/run status."""
    if origin is None:
        return None
    if not isinstance(origin, dict) or set(origin) - {'session_id', 'run_id'}:
        raise OriginError('动作来源格式无效')
    sid = origin.get('session_id')
    if not isinstance(sid, str) or not sid.strip() or len(sid) > 128:
        raise OriginError('来源会话 ID 格式无效')
    result = {'session_id': sid}
    if 'run_id' in origin:
        rid = origin['run_id']
        if not isinstance(rid, str) or not rid.strip() or len(rid) > 128:
            raise OriginError('来源任务 ID 格式无效')
        result['run_id'] = rid
    return result


def _has_table(db, table):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def resolve(db, origin, object_id):
    """Call inside the same write transaction that inserts the action."""
    origin = normalize(origin)
    if origin is None:
        return None
    if not db.in_transaction:
        raise RuntimeError('动作来源校验必须位于动作写入事务内')
    sid = origin['session_id']
    if not _has_table(db, 'assistant_sessions'):
        raise OriginError('来源会话不存在', 404)
    row = db.execute('SELECT payload FROM assistant_sessions WHERE id=?', (sid,)).fetchone()
    if not row:
        raise OriginError('来源会话不存在', 404)
    session = json.loads(row[0])
    if (session.get('target') or {}).get('id') != object_id:
        raise OriginError('来源会话的目标与动作目标不一致', 409)
    has_runs = _has_table(db, 'assistant_runs')
    runs = {}
    if has_runs:
        for run_row in db.execute('SELECT id,payload FROM assistant_runs WHERE session_id=?', (sid,)):
            run = json.loads(run_row[1])
            runs[run_row[0]] = run
            if run.get('status') not in TERMINAL:
                raise OriginError('来源会话仍有活动任务，请等待完成或取消后再生成提案', 409)
    active_id = session.get('active_run_id')
    if active_id and active_id not in runs:
        raise OriginError('来源会话任务状态尚不能确认，请刷新后重试', 409)
    title = session.get('title', '')
    snapshot = dict(session_id=sid, title=title[:120] if isinstance(title, str) else '',
                    mode=session.get('mode') if session.get('mode') in {'demo', 'readonly'} else 'unknown', object_id=object_id)
    if 'run_id' in origin:
        rid = origin['run_id']
        run = runs.get(rid)
        if run is None:
            raise OriginError('来源任务不存在或不属于此会话', 404)
        if run.get('session_id') != sid or (run.get('target') or {}).get('id') != object_id:
            raise OriginError('来源任务与会话或动作目标不一致', 409)
        if run.get('status') not in TERMINAL:
            raise OriginError('来源任务尚未结束', 409)
        snapshot.update(run_id=rid, run_status=run['status'])
    return snapshot


def list_for_session(connection, sid):
    """Read historical snapshots even after the originating session is deleted."""
    if not isinstance(sid, str) or not sid.strip() or len(sid) > 128:
        raise OriginError('会话 ID 格式无效')
    actions = []
    with connection() as db:
        for table, family in ACTION_TABLES:
            if not _has_table(db, table):
                continue
            # Table names come exclusively from the constant allowlist above.
            for row in db.execute('SELECT payload FROM ' + table):
                action = json.loads(row[0])
                if isinstance(action.get('origin'), dict) and action['origin'].get('session_id') == sid:
                    actions.append({**action, 'family': family})
    actions.sort(key=lambda action: (action.get('updated_at', ''), action.get('created_at', ''), action.get('id', '')), reverse=True)
    return actions
