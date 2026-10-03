from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cleanup_store as store


class CleanupStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'test.sqlite'
        self.directory = Path(self.temp.name) / 'fixture'
        self.directory.mkdir()
        self.file = self.directory / 'keep.txt'
        self.file.write_text('keep')
        self.objects = [dict(id='directory-a', kind='directory', name='Fixture', path=str(self.directory), retention='未标记')]
        self.summary = dict(path=str(self.directory), fingerprint='fixture-hash', files=1, directories=0, bytes=4, processes=[], usage_check='partial', restore_note='仅在回收站手动恢复')
        store.initialize(self.connection)
        self.preview_patch = patch.object(store.recycle_action, 'preview', side_effect=lambda *args: dict(self.summary))
        self.preview_patch.start()
        self.apply_patch = patch.object(store.recycle_action, 'apply', return_value={'state': 'recycled', 'path': str(self.directory)})
        self.apply = self.apply_patch.start()

    def tearDown(self):
        self.preview_patch.stop()
        self.apply_patch.stop()
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
        return store.dispatch(self.connection, '/api/cleanup/' + route, body, self.objects, [Path(self.temp.name) / 'protected'])

    def propose(self, request='r'):
        return self.call('propose', object_id=self.objects[0]['id'], kind='recycle', request_id=request)[0]['action']

    def test_preview_no_write_and_confirm_journal_precedes_idempotent_execution(self):
        action = self.propose()
        self.assertEqual(action['preview']['usage_check'], 'partial')
        self.assertEqual(self.file.read_text(), 'keep')
        self.apply.assert_not_called()
        self.assertEqual(self.call('confirm', id=action['id'], revision=1, acknowledge=False)[1], 400)
        def execute(*args):
            with self.connection() as db:
                current = json.loads(db.execute('SELECT payload FROM cleanup_actions').fetchone()[0])
            self.assertEqual(current['state'], 'executing')
            return {'state': 'recycled', 'fixture': True}
        self.apply.side_effect = execute
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.call('confirm', id=action['id'], revision=1, acknowledge=True), range(6)))
        self.assertTrue(all(status == 200 for _, status in results))
        self.apply.assert_called_once()
        self.assertEqual(self.file.read_text(), 'keep')

    def test_retention_and_fingerprint_conflict_block_execution(self):
        self.objects[0]['retention'] = '保留'
        self.assertEqual(self.call('propose', object_id='directory-a', kind='recycle', request_id='r')[1], 409)
        self.objects[0]['retention'] = '未标记'
        action = self.propose()
        self.objects[0]['retention'] = '保留'
        self.assertEqual(self.call('confirm', id=action['id'], revision=1, acknowledge=True)[1], 409)
        self.objects[0]['retention'] = '未标记'
        action = self.propose('second')
        self.summary['fingerprint'] = 'changed'
        payload, status = self.call('confirm', id=action['id'], revision=1, acknowledge=True)
        self.assertEqual((status, payload['action']['state']), (409, 'conflict'))
        self.apply.assert_not_called()

    def test_interrupted_execution_never_replays(self):
        action = self.propose()
        self.apply.side_effect = SystemExit('simulated crash')
        with self.assertRaises(SystemExit):
            self.call('confirm', id=action['id'], revision=1, acknowledge=True)
        store.initialize(self.connection)
        recovered = self.call('list')[0]['actions'][0]
        self.assertEqual(recovered['state'], 'interrupted')
        self.assertEqual(self.call('confirm', id=action['id'], revision=1, acknowledge=True)[1], 409)
        self.apply.assert_called_once()
        self.assertEqual(self.file.read_text(), 'keep')

    def test_failure_is_safe_and_arbitrary_targets_are_rejected(self):
        self.assertEqual(self.call('propose', object_id='directory-a', kind='recycle', request_id='r', path='C:/arbitrary')[1], 400)
        action = self.propose()
        self.apply.side_effect = ValueError('secret fixture raw diagnostic')
        payload, status = self.call('confirm', id=action['id'], revision=1, acknowledge=True)
        self.assertEqual((status, payload['action']['state']), (500, 'failed'))
        self.assertNotIn('secret fixture', json.dumps(payload))

    def test_uncertain_receipt_persists_and_verify_retains_execution_error(self):
        action = self.propose()
        failure = ValueError('raw secret diagnostic')
        failure.receipt = {'state': 'uncertain', 'path': 'untrusted exception path', 'restore_note': 'raw secret diagnostic', 'raw': 'secret'}
        self.apply.side_effect = failure
        payload, status = self.call('confirm', id=action['id'], revision=1, acknowledge=True)
        self.assertEqual(status, 500)
        receipt = payload['action']['receipt']
        self.assertEqual(receipt['state'], 'uncertain')
        self.assertEqual(receipt['path'], str(self.directory))
        self.assertNotIn('secret', json.dumps(receipt))
        original_error = payload['action']['error']
        payload, status = self.call('verify', id=action['id'])
        self.assertEqual(status, 200)
        self.assertEqual(payload['action']['error'], original_error)
        self.assertTrue(payload['action']['verification']['path_exists'])

    def test_msi_waiting_user_and_verify_survive_disappeared_inventory(self):
        self.objects = [dict(id='software-a', kind='software', name='Fixture MSI', windowsInstaller=True, registryHive='HKLM', registryView=256, registryKey='{12345678-1234-1234-1234-123456789ABC}')]
        with patch.object(store.msi_action, 'preview', return_value={'fingerprint': 'msi-fixture', 'product_code': self.objects[0]['registryKey']}), patch.object(store.msi_action, 'apply', return_value={'state': 'waiting_user', 'pid': 123}) as launch:
            action = self.call('propose', object_id='software-a', kind='uninstall', request_id='msi')[0]['action']
            result = self.call('confirm', id=action['id'], revision=1, acknowledge=True)[0]['action']
            self.assertEqual(result['state'], 'waiting_user')
            self.call('confirm', id=action['id'], revision=1, acknowledge=True)
            launch.assert_called_once()
        self.objects = []
        with patch.object(store.msi_action, 'verify', return_value={'state': 'still_registered'}):
            self.assertEqual(self.call('verify', id=action['id'])[0]['action']['state'], 'still_registered')
        with patch.object(store.msi_action, 'verify', return_value={'state': 'removed'}) as verify:
            self.assertEqual(self.call('verify', id=action['id'])[0]['action']['state'], 'removed')
            self.assertEqual(verify.call_args.args[0]['registryKey'], action['object']['registryKey'])
        self.assertEqual(self.call('list')[0]['actions'][0]['object']['name'], 'Fixture MSI')


if __name__ == '__main__':
    unittest.main()
