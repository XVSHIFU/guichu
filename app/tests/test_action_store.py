from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from action_store import dispatch, initialize


class ActionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'actions.sqlite'
        self.objects = [dict(id='a', name='Alpha', path='C:/a', kind='directory', source='测试')]
        with self.connection() as db:
            db.execute('CREATE TABLE notes (id TEXT PRIMARY KEY, decision TEXT, body TEXT, updated TEXT)')
            db.execute('PRAGMA user_version=7')
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

    def call(self, route, **body):
        return dispatch(self.connection, '/api/action/' + route, body, self.objects)

    def propose(self, request='r'):
        return self.call('propose', object_id='a', decision='保留', request_id=request)[0]['action']

    def note(self):
        with self.connection() as db:
            return db.execute('SELECT id,decision,body,updated FROM notes WHERE id=?', ('a',)).fetchone()

    def write_note(self, decision='待确认', body='原备注', updated='original-time'):
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO notes VALUES (?,?,?,?)', ('a', decision, body, updated))

    def test_propose_is_readonly_and_migrations_preserve_notes(self):
        self.write_note()
        before = self.note()
        action = self.propose()
        self.assertEqual(self.note(), before)
        self.assertEqual(action['before']['updated'], 'original-time')
        self.assertEqual(action['after']['body'], '原备注')
        self.assertEqual(action['state'], 'pending')
        initialize(self.connection)
        with self.connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 7)
        self.assertEqual(self.call('list')[0]['actions'][0]['id'], action['id'])

    def test_concurrent_confirm_is_idempotent_and_restores_full_note(self):
        self.write_note()
        before = self.note()
        action = self.propose()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.call('confirm', id=action['id'], revision=1), range(8)))
        self.assertTrue(all(status == 200 for _, status in results))
        self.assertEqual(len({payload['action']['after']['updated'] for payload, _ in results}), 1)
        self.assertEqual(self.note()[1:3], ('保留', '原备注'))
        self.assertEqual(self.call('restore', id=action['id'], revision=1)[1], 200)
        self.assertEqual(self.note(), before)
        self.write_note(body='恢复后编辑')
        self.assertEqual(self.call('restore', id=action['id'], revision=1)[1], 200)
        self.assertEqual(self.note()[2], '恢复后编辑')
        self.assertEqual(self.call('confirm', id=action['id'], revision=1)[1], 409)

    def test_new_note_restore_deletes_only_created_record(self):
        action = self.propose()
        self.call('confirm', id=action['id'], revision=1)
        self.objects = []
        self.assertEqual(self.call('restore', id=action['id'], revision=1)[1], 200)
        self.assertIsNone(self.note())

    def test_confirm_conflict_never_overwrites_external_edit(self):
        self.write_note()
        action = self.propose()
        self.write_note(updated='external-change')
        payload, status = self.call('confirm', id=action['id'], revision=1)
        self.assertEqual(status, 409)
        self.assertEqual(payload['action']['state'], 'conflict')
        self.assertEqual(self.note()[3], 'external-change')

    def test_restore_conflict_and_confirm_retry_preserve_new_edit(self):
        action = self.propose()
        self.call('confirm', id=action['id'], revision=1)
        self.write_note(body='新的备注')
        self.assertEqual(self.call('confirm', id=action['id'], revision=1)[1], 200)
        payload, status = self.call('restore', id=action['id'], revision=1)
        self.assertEqual(status, 409)
        self.assertEqual(payload['action']['state'], 'restore_conflict')
        self.assertEqual(self.note()[2], '新的备注')

    def test_request_conflicts_revision_validation_and_missing_target(self):
        action = self.propose()
        self.assertEqual(self.propose()['id'], action['id'])
        self.assertEqual(self.call('propose', object_id='a', decision='待确认', request_id='r')[1], 409)
        self.assertEqual(self.call('confirm', id=action['id'], revision=True)[1], 409)
        self.assertEqual(self.call('confirm', id='missing', revision=1)[1], 404)
        self.objects = []
        self.assertEqual(self.propose()['id'], action['id'])
        self.assertEqual(self.call('propose', object_id='a', decision='保留', request_id='new')[1], 404)
        payload, status = self.call('confirm', id=action['id'], revision=1)
        self.assertEqual(status, 409)
        self.assertEqual(payload['action']['state'], 'conflict')
        self.assertIsNone(self.note())
        self.assertEqual(self.call('propose', object_id='a', decision=[], request_id='bad')[1], 400)


if __name__ == '__main__':
    unittest.main()
