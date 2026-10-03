from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mcp_action_store as store


class MCPActionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db = root / 'test.sqlite'
        self.config = root / 'config.toml'
        self.backups = root / 'backups'
        self.original = b'# keep\n[mcp_servers.sample]\ncommand="test"\nenabled=true\n[mcp_servers.sample.env]\nTOKEN="secret-fixture"\n'
        self.config.write_bytes(self.original)
        self.objects = [dict(id='mcp:test', name='sample', kind='mcp', scope='codex', source='用户配置', path=str(self.config))]
        store.initialize(self.connection)

    def tearDown(self):
        self.temp.cleanup()

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.db, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def call(self, route, **body):
        return store.dispatch(self.connection, '/api/mcp-action/' + route, body, self.objects, self.config, self.backups)

    def propose(self, request='request'):
        payload, status = self.call('propose', object_id='mcp:test', enabled=False, request_id=request)
        self.assertEqual(status, 200)
        return payload['action']

    def test_preview_apply_restore_real_toml_and_receipt_precedes_write(self):
        action = self.propose()
        self.assertEqual(action['backup_location'], str(self.backups.absolute()))
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertFalse(self.backups.exists())
        replace = store.adapter._replace
        def observed_replace(*args):
            with self.connection() as db:
                saved = json.loads(db.execute('SELECT payload FROM mcp_actions').fetchone()[0])
            self.assertEqual(saved['state'], 'applying')
            self.assertEqual(Path(saved['receipt']['backup_path']).read_bytes(), self.original)
            return replace(*args)
        with patch.object(store.adapter, '_replace', side_effect=observed_replace):
            payload, status = self.call('confirm', id=action['id'], revision=1)
        self.assertEqual(status, 200)
        self.assertEqual(payload['action']['state'], 'applied')
        self.assertNotIn('secret-fixture', json.dumps(payload))
        self.assertEqual(self.config.read_bytes(), self.original.replace(b'enabled=true', b'enabled=false'))
        self.assertEqual(self.call('restore', id=action['id'], revision=1)[1], 200)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_concurrent_confirm_and_request_retries_are_idempotent(self):
        action = self.propose()
        self.assertEqual(self.propose()['id'], action['id'])
        self.assertEqual(self.call('propose', object_id='mcp:test', enabled=True, request_id='request')[1], 409)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.call('confirm', id=action['id'], revision=1), range(6)))
        self.assertTrue(all(status == 200 for _, status in results))
        self.assertEqual(len(list(self.backups.iterdir())), 1)
        self.call('restore', id=action['id'], revision=1)
        self.config.write_bytes(self.original + b'# later\n')
        self.assertEqual(self.call('restore', id=action['id'], revision=1)[1], 200)
        self.assertTrue(self.config.read_bytes().endswith(b'# later\n'))

    def test_conflict_before_confirm_and_after_apply_preserves_external_changes(self):
        action = self.propose()
        external = self.original + b'# change\n'
        self.config.write_bytes(external)
        payload, status = self.call('confirm', id=action['id'], revision=1)
        self.assertEqual((status, payload['action']['state']), (409, 'conflict'))
        self.assertEqual(self.config.read_bytes(), external)
        self.assertFalse(self.backups.exists())
        action = self.propose('second')
        self.call('confirm', id=action['id'], revision=1)
        external = self.config.read_bytes() + b'# newest\n'
        self.config.write_bytes(external)
        payload, status = self.call('restore', id=action['id'], revision=1)
        self.assertEqual((status, payload['action']['state']), (409, 'restore_conflict'))
        self.assertEqual(self.config.read_bytes(), external)

    def test_scope_paths_and_revision_cannot_be_client_selected(self):
        self.assertEqual(self.call('propose', object_id='mcp:test', enabled=False, request_id='r', path=str(self.config))[1], 400)
        self.assertEqual(self.call('propose', object_id='mcp:test', enabled=0, request_id='r')[1], 400)
        for field, value in [('scope', 'claude'), ('source', '插件附带'), ('path', str(self.config.parent / 'other.toml')), ('kind', 'plugin')]:
            original = self.objects[0][field]
            self.objects[0][field] = value
            self.assertEqual(self.call('propose', object_id='mcp:test', enabled=False, request_id='r')[1], 404)
            self.objects[0][field] = original
        action = self.propose()
        self.assertEqual(self.call('confirm', id=action['id'], revision=True)[1], 409)
        self.objects = []
        self.assertEqual(self.call('confirm', id=action['id'], revision=1)[1], 409)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_crash_after_replace_keeps_receipt_and_restart_only_marks_interrupted(self):
        action = self.propose()
        replace = store.adapter._replace
        def crash(*args):
            replace(*args)
            raise SystemExit('simulated process interruption')
        with patch.object(store.adapter, '_replace', side_effect=crash), self.assertRaises(SystemExit):
            self.call('confirm', id=action['id'], revision=1)
        applied_bytes = self.config.read_bytes()
        store.initialize(self.connection)
        recovered = self.call('list')[0]['actions'][0]
        self.assertEqual(recovered['state'], 'interrupted')
        self.assertTrue(recovered['receipt'])
        self.assertEqual(recovered['observed_state'], 'matches_after')
        self.assertEqual(self.config.read_bytes(), applied_bytes)
        self.assertEqual(self.call('restore', id=action['id'], revision=1)[1], 200)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_failed_replace_receipt_survives_but_wrong_after_hash_blocks_restore(self):
        action = self.propose()
        with patch.object(store.adapter.os, 'replace', side_effect=PermissionError('secret-fixture')):
            payload, status = self.call('confirm', id=action['id'], revision=1)
        self.assertEqual((status, payload['action']['state']), (500, 'failed'))
        self.assertTrue(payload['action']['receipt'])
        self.assertNotIn('secret-fixture', json.dumps(payload))
        self.assertEqual(self.call('restore', id=action['id'], revision=1)[1], 409)
        self.assertEqual(self.config.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
