from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import action_origin
import action_store
import assistant_store
import assistant_runtime
import cleanup_store
import mcp_action_store


class ActionOriginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / 'test.sqlite'
        self.config = self.root / 'config.toml'
        self.config.write_text('[mcp_servers.fixture]\nenabled=true\n', encoding='utf-8')
        self.directory = self.root / 'sample'
        self.directory.mkdir()
        self.objects = [dict(id='directory', kind='directory', name='Sample', path=str(self.directory)),
                        dict(id='mcp', kind='mcp', scope='codex', source='用户配置', name='fixture', path=str(self.config))]
        with self.connection() as db:
            db.execute('CREATE TABLE notes (id TEXT PRIMARY KEY, decision TEXT, body TEXT, updated TEXT)')
        assistant_store.initialize(self.connection)
        assistant_runtime.initialize(self.connection)
        action_store.initialize(self.connection)
        mcp_action_store.initialize(self.connection)
        cleanup_store.initialize(self.connection)
        self.add_session('session')
        self.add_session('other-session')
        self.preview_patch = patch.object(cleanup_store.recycle_action, 'preview', return_value={'fingerprint': 'mock-fingerprint', 'files': 0, 'directories': 0, 'bytes': 0, 'usage_check': 'partial', 'restore_note': 'fixture'})
        self.preview_patch.start()

    def tearDown(self):
        self.preview_patch.stop()
        self.temp.cleanup()

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.db, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def add_session(self, sid, target='directory', **extra):
        payload = dict(id=sid, title='来源标题', mode='readonly', target={'id': target}, messages=[{'text': 'secret-message'}], draft='secret-draft', active_run_id=None, **extra)
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO assistant_sessions VALUES (?,?)', (sid, json.dumps(payload)))

    def target(self, target):
        with self.connection() as db:
            payload = json.loads(db.execute('SELECT payload FROM assistant_sessions WHERE id=?', ('session',)).fetchone()[0])
            payload['target'] = {'id': target}
            db.execute('UPDATE assistant_sessions SET payload=? WHERE id=?', (json.dumps(payload), 'session'))

    def add_run(self, rid='run', sid='session', target='directory', status='succeeded', payload_sid=None):
        payload = dict(id=rid, session_id=payload_sid or sid, target={'id': target}, status=status, answer='secret-answer', input='secret-input')
        with self.connection() as db:
            db.execute('INSERT INTO assistant_runs VALUES (?,?,?,?)', (rid, sid, rid, json.dumps(payload)))

    def propose(self, family, request='request', origin=None, include=True):
        target = 'mcp' if family == 'mcp-action' else 'directory'
        body = dict(object_id=target, request_id=request)
        if include:
            body['origin'] = origin if origin is not None else {'session_id': 'session'}
        if family == 'action':
            body['decision'] = '保留'
            return action_store.dispatch(self.connection, '/api/action/propose', body, self.objects)
        if family == 'mcp-action':
            body['enabled'] = False
            return mcp_action_store.dispatch(self.connection, '/api/mcp-action/propose', body, self.objects, self.config, self.root/'backups')
        body['kind'] = 'recycle'
        return cleanup_store.dispatch(self.connection, '/api/cleanup/propose', body, self.objects, [])

    def test_all_families_bind_snapshot_in_transaction_and_cross_table_list(self):
        for family in ('action', 'mcp-action', 'cleanup'):
            self.target('mcp' if family == 'mcp-action' else 'directory')
            payload, status = self.propose(family)
            self.assertEqual(status, 200)
            origin = payload['action']['origin']
            self.assertEqual(origin['session_id'], 'session')
            self.assertEqual(origin['title'], '来源标题')
            self.assertEqual(set(origin), {'session_id', 'title', 'mode', 'object_id'})
            self.assertNotIn('secret', json.dumps(origin))
        linked = action_origin.list_for_session(self.connection, 'session')
        self.assertEqual({item['family'] for item in linked}, {'action', 'mcp-action', 'cleanup'})
        self.assertEqual(len(linked), 3)

    def test_wrong_target_and_active_run_rejected_in_all_families(self):
        for family in ('action', 'mcp-action', 'cleanup'):
            self.target('other-target')
            self.assertEqual(self.propose(family, request=family+'-wrong')[1], 409)
            target = 'mcp' if family == 'mcp-action' else 'directory'
            self.target(target)
            self.add_run(rid=family+'-active', target=target, status='running')
            self.assertEqual(self.propose(family, request=family+'-active')[1], 409)
            with self.connection() as db:
                db.execute('DELETE FROM assistant_runs')

    def test_run_must_belong_to_session_match_target_and_be_terminal(self):
        self.add_run('wrong-session', sid='other-session')
        self.assertEqual(self.propose('action', origin={'session_id': 'session', 'run_id': 'wrong-session'})[1], 404)
        self.add_run('wrong-target', target='mcp')
        self.assertEqual(self.propose('action', origin={'session_id': 'session', 'run_id': 'wrong-target'})[1], 409)
        self.add_run('right')
        payload, status = self.propose('action', origin={'session_id': 'session', 'run_id': 'right'})
        self.assertEqual(status, 200)
        self.assertEqual(payload['action']['origin']['run_status'], 'succeeded')
        self.assertNotIn('secret', json.dumps(payload['action']['origin']))

    def test_origin_change_conflicts_retry_survives_deleted_session(self):
        for family in ('action', 'mcp-action', 'cleanup'):
            self.target('mcp' if family == 'mcp-action' else 'directory')
            original, status = self.propose(family)
            self.assertEqual(status, 200)
            self.assertEqual(self.propose(family, origin={'session_id': 'other-session'})[1], 409)
            self.assertEqual(self.propose(family, include=False)[1], 409)
            self.assertEqual(self.propose(family)[0]['action']['id'], original['action']['id'])
        assistant_store.dispatch(self.connection, '/api/assistant/delete', {'id': 'session'}, self.objects)
        linked = action_origin.list_for_session(self.connection, 'session')
        self.assertEqual(len(linked), 3)
        self.assertTrue(all(action['origin']['title'] == '来源标题' for action in linked))
        for family in ('action', 'mcp-action', 'cleanup'):
            self.assertEqual(self.propose(family)[1], 200)
            self.assertEqual(self.propose(family, request='new')[1], 404)

    def test_legacy_request_payloads_remain_compatible(self):
        for family in ('action', 'mcp-action', 'cleanup'):
            original, status = self.propose(family, include=False)
            self.assertEqual(status, 200)
            self.assertNotIn('origin', original['action'])
            self.assertEqual(self.propose(family, include=False)[0]['action']['id'], original['action']['id'])
            self.assertEqual(self.propose(family)[1], 409)

    def test_missing_tables_and_invalid_metadata(self):
        empty = self.root / 'empty.sqlite'
        @contextmanager
        def empty_connection():
            db = sqlite3.connect(empty)
            try:
                with db:
                    yield db
            finally:
                db.close()
        self.assertEqual(action_origin.list_for_session(empty_connection, 'session'), [])
        for origin in ({}, {'session_id': []}, {'session_id': 'session', 'run_id': ''}, {'session_id': 'session', 'title': 'forged'}):
            self.assertEqual(self.propose('action', origin=origin)[1], 400)


if __name__ == '__main__':
    unittest.main()
