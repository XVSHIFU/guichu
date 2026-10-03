import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from assistant_store import dispatch, initialize


class AssistantStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.sqlite'
        self.objects = [dict(id='a', name='Alpha', path='C:/a', kind='directory', source='test'),
                        dict(id='b', name='Beta', path='C:/b', kind='directory', source='test')]
        initialize(self.connection)

    def tearDown(self):
        self.temp.cleanup()

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def call(self, action, **body):
        return dispatch(self.connection, '/api/assistant/' + action, body, self.objects)

    def create(self):
        return self.call('create', target_id='a')[0]['session']['id']

    def seed_legacy(self):
        session = dict(id='legacy', title='Old conversation', updated_at='2026-01-01', mode='demo',
                       draft='unfinished', target=self.objects[0],
                       messages=[dict(id='m1', role='user', text='old question'),
                                 dict(id='m2', role='assistant', text='old demonstration')],
                       plan=dict(id='p1', target_id='a', request='old question', name='Alpha',
                                 path='C:/a', kind='directory', source='test'), accepted=True)
        payload = json.dumps(session, indent=2)
        with self.connection() as db:
            db.execute('INSERT INTO assistant_sessions VALUES (?, ?)', (session['id'], payload))
            db.execute('INSERT INTO assistant_requests VALUES (?, ?, ?)', ('legacy', 'r1', 'old request'))
        return session, payload

    def test_new_sessions_are_readonly_without_generated_content(self):
        for body in ({}, {'target_id': 'a'}):
            result, status = self.call('create', **body)
            self.assertEqual(status, 200)
            session = result['session']
            self.assertEqual(session['mode'], 'readonly')
            self.assertEqual(session['messages'], [])
            self.assertIsNone(session['active_run_id'])
            self.assertNotIn('plan', session)
            self.assertNotIn('accepted', session)

    def test_restart_and_existing_database_preserved(self):
        with self.connection() as db:
            db.execute('CREATE TABLE notes (body TEXT)')
            db.execute("INSERT INTO notes VALUES ('keep')")
            db.execute('PRAGMA user_version=7')
        sid = self.create()
        self.call('update', id=sid, draft='unfinished', title='title')
        initialize(self.connection)
        self.assertEqual(self.call('get', id=sid)[0]['session']['draft'], 'unfinished')
        with self.connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 7)
            self.assertEqual(db.execute('SELECT body FROM notes').fetchone()[0], 'keep')

    def test_legacy_history_is_preserved_exactly_and_disabled_endpoints_do_not_write(self):
        session, payload = self.seed_legacy()
        initialize(self.connection)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda i: self.call('send' if i % 2 else 'confirm',
                id='legacy', text='new request', request_id='r1', proposal_id='p1'), range(8)))
        self.assertTrue(all(status == 410 for _, status in results))
        self.assertTrue(all('/api/run/start' in result['error'] for result, _ in results))
        self.assertEqual(self.call('get', id='legacy')[0]['session'], session)
        self.assertEqual(self.call('list')[0]['sessions'][0]['mode'], 'demo')
        with self.connection() as db:
            self.assertEqual(db.execute('SELECT payload FROM assistant_sessions').fetchone()[0], payload)
            self.assertEqual(db.execute('SELECT * FROM assistant_requests').fetchall(), [('legacy', 'r1', 'old request')])

    def test_disabled_endpoints_never_open_database_even_for_invalid_inputs(self):
        def forbidden_connection():
            raise AssertionError('retired endpoint accessed storage')
        for action in ('send', 'confirm'):
            for body in (None, [], {}, {'id': 'missing'}):
                self.assertEqual(dispatch(forbidden_connection, '/api/assistant/' + action, body, [])[1], 410)

    def test_migrates_unversioned_tables_without_rewriting_history(self):
        _, payload = self.seed_legacy()
        with self.connection() as db:
            db.execute('DROP TABLE assistant_meta')
            db.execute('DROP TABLE assistant_requests')
            db.execute('CREATE TABLE assistant_requests (session_id TEXT, request_id TEXT, PRIMARY KEY(session_id, request_id))')
            db.execute('INSERT INTO assistant_requests VALUES (?, ?)', ('legacy', 'r1'))
        initialize(self.connection)
        initialize(self.connection)
        with self.connection() as db:
            self.assertEqual(db.execute("SELECT value FROM assistant_meta WHERE key='schema_version'").fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT * FROM assistant_requests').fetchall(), [('legacy', 'r1', None)])
            self.assertEqual(db.execute('SELECT payload FROM assistant_sessions').fetchone()[0], payload)

    def test_legacy_crud_preserves_historical_fields(self):
        original, _ = self.seed_legacy()
        result, status = self.call('update', id='legacy', title='Renamed', draft='new draft', target_id='b')
        self.assertEqual(status, 200)
        session = result['session']
        for key in ('messages', 'plan', 'accepted', 'mode'):
            self.assertEqual(session[key], original[key])
        self.assertEqual(session['target']['id'], 'b')
        self.assertEqual(session['title'], 'Renamed')
        self.assertEqual(session['draft'], 'new draft')
        self.assertEqual(self.call('delete', id='legacy')[1], 200)
        with self.connection() as db:
            self.assertEqual(db.execute('SELECT * FROM assistant_requests').fetchall(), [])

    def test_missing_target_preserves_history_and_rejects_invalid_update(self):
        original, payload = self.seed_legacy()
        self.objects = []
        self.assertEqual(self.call('get', id='legacy')[0]['session'], original)
        self.assertEqual(self.call('update', id='legacy', title='Changed', target_id='a')[1], 400)
        with self.connection() as db:
            self.assertEqual(db.execute('SELECT payload FROM assistant_sessions').fetchone()[0], payload)
        self.assertIsNone(self.call('update', id='legacy', target_id=None)[0]['session']['target'])

    def test_validation_delete_and_list(self):
        sid = self.create()
        self.assertEqual(self.call('update', id=sid, draft=123)[1], 400)
        self.assertEqual(self.call('update', id=sid, title=' ')[1], 400)
        self.assertEqual(self.call('create', target_id='missing')[1], 400)
        self.assertEqual(self.call('get', id=[])[1], 404)
        self.assertEqual(len(self.call('list')[0]['sessions']), 1)
        self.assertEqual(self.call('delete', id=sid)[1], 200)
        self.assertEqual(self.call('get', id=sid)[1], 404)
        self.assertEqual(self.call('list')[0]['sessions'], [])


if __name__ == '__main__':
    unittest.main()
