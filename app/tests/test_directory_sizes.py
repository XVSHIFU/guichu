from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import directory_sizes as sizes


class DirectorySizeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.directory = self.root / 'tree'
        self.directory.mkdir()
        self.db = self.root / 'tasks.sqlite'
        self.mounts = patch.object(sizes.psutil, 'disk_partitions', return_value=[
            SimpleNamespace(mountpoint=self.root.anchor, opts='rw')])
        self.mounts.start()
        self.gates = []
        self.ids = []
        sizes.initialize(self.connection)

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.db, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def tearDown(self):
        for rid in self.ids:
            self.call('cancel', id=rid)
        for gate in self.gates:
            gate.set()
        for rid in self.ids:
            self.wait(rid)
        self.mounts.stop()
        self.temp.cleanup()

    def call(self, action, **body):
        return sizes.dispatch(self.connection, '/api/size/' + action, body)

    def start(self, request_id='one', path=None):
        payload, status = self.call('start', path=str(path or self.directory), request_id=request_id)
        if 'task' in payload:
            self.ids.append(payload['task']['id'])
        return payload, status

    def wait(self, rid):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            task = self.call('get', id=rid)[0]['task']
            with sizes.LOCK:
                active = rid in sizes.ACTIVE
            if task['status'] in sizes.TERMINAL and not active:
                return task
            time.sleep(.01)
        self.fail('directory task did not terminate')

    def test_metadata_size_hardlinks_and_persistence(self):
        (self.directory / 'nested').mkdir()
        (self.directory / 'first').write_bytes(b'a' * 17)
        (self.directory / 'nested' / 'second').write_bytes(b'b' * 23)
        os.link(self.directory / 'first', self.directory / 'hardlink')
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('no content reads')):
            payload, status = self.start()
            self.assertEqual(status, 202)
            task = self.wait(payload['task']['id'])
        self.assertEqual(task['status'], 'succeeded')
        self.assertEqual((task['bytes'], task['files'], task['directories'], task['hardlinks']), (40, 2, 2, 1))
        tree={node['name']:node for node in task['tree']}
        self.assertEqual(tree['nested']['bytes'],23)
        self.assertTrue(tree['nested']['complete'])
        self.assertEqual(tree[self.directory.name]['bytes'],40)
        self.assertEqual(task['largest_files'][0]['bytes'],23)
        sizes.initialize(self.connection)
        self.assertEqual(self.call('get', id=task['id'])[0]['task'], task)
        self.assertEqual(self.call('list')[0]['tasks'][0]['id'], task['id'])

    def test_entry_and_time_limits_produce_partial(self):
        for i in range(5):
            (self.directory / str(i)).write_bytes(b'abc')
        with patch.object(sizes, 'MAX_ENTRIES', 2):
            payload, _ = self.start()
            task = self.wait(payload['task']['id'])
        self.assertEqual((task['status'], task['limit'], task['entries']), ('partial', 'entries', 2))
        with patch.object(sizes, 'MAX_SECONDS', 0):
            payload, _ = self.start('two')
            task = self.wait(payload['task']['id'])
        self.assertEqual((task['status'], task['limit']), ('partial', 'time'))

    def test_cancel_single_active_and_retry_idempotence(self):
        (self.directory / 'first').touch()
        entered, release = threading.Event(), threading.Event()
        self.gates.append(release)
        original = sizes.os.scandir
        def blocked(path):
            entered.set()
            release.wait(3)
            return original(path)
        with patch.object(sizes.os, 'scandir', side_effect=blocked):
            payload, _ = self.start()
            rid = payload['task']['id']
            self.assertTrue(entered.wait(2))
            self.assertTrue(sizes.is_running())
            self.assertEqual(self.start('two')[1], 409)
            retry, status = self.start()
            self.assertEqual((status, retry['task']['id']), (200, rid))
            self.assertEqual(self.start(path=self.root)[1], 409)
            self.assertTrue(self.call('cancel', id=rid)[0]['task']['cancel_requested'])
            release.set()
            task = self.wait(rid)
        self.assertEqual(task['status'], 'cancelled')
        self.assertEqual(task['entries'], 0)
        self.assertFalse(sizes.is_running())

    def test_permission_error_reports_partial(self):
        (self.directory / 'denied').mkdir()
        (self.directory / 'file').write_bytes(b'abc')
        original = sizes.os.scandir
        def scan(path):
            if Path(path).name == 'denied':
                raise PermissionError('fixture')
            return original(path)
        with patch.object(sizes.os, 'scandir', side_effect=scan):
            payload, _ = self.start()
            task = self.wait(payload['task']['id'])
        self.assertEqual((task['status'], task['errors'], task['bytes']), ('partial', 1, 3))
        self.assertEqual(task['issue_counts'], {'permission': 1})
        self.assertTrue(task['issue_samples'][0]['path'].endswith('denied'))

    def test_cancel_is_observed_between_entries_and_keeps_progress(self):
        for i in range(10):
            (self.directory / str(i)).write_bytes(b'abc')
        original = sizes._persist
        def persist(connection, task):
            original(connection, task)
            if task['entries'] == 2 and task['status'] == 'running':
                with sizes.LOCK:
                    sizes.ACTIVE[task['id']].set()
        with patch.object(sizes, '_persist', side_effect=persist), patch.object(sizes, 'PROGRESS_INTERVAL', 0):
            payload, _ = self.start()
            task = self.wait(payload['task']['id'])
        self.assertEqual((task['status'], task['entries'], task['bytes']), ('cancelled', 2, 6))

    def test_child_junction_skipped_without_traversal(self):
        linked = self.directory / 'linked'
        linked.mkdir()
        (linked / 'hidden').write_bytes(b'abcdef')
        original = Path.is_junction
        with patch.object(Path, 'is_junction', lambda path: path == linked or original(path)):
            payload, _ = self.start()
            task = self.wait(payload['task']['id'])
        self.assertEqual((task['status'], task['skipped'], task['bytes'], task['directories']), ('partial', 1, 0, 1))

    def test_restart_marks_queued_interrupted_without_replay(self):
        with patch.object(sizes.threading, 'Thread'):
            payload, _ = self.start()
        rid = payload['task']['id']
        with sizes.LOCK:
            sizes.ACTIVE.pop(rid)
        sizes.initialize(self.connection)
        task = self.wait(rid)
        self.assertEqual(task['status'], 'interrupted')
        sizes.initialize(self.connection)
        self.assertEqual(self.call('get', id=rid)[0]['task'], task)

    def test_unvisited_sibling_is_not_reported_complete(self):
        for name in ('Windows', 'Users'):
            (self.directory / name).mkdir()
            (self.directory / name / 'file').write_bytes(b'abc')
        with patch.object(sizes, 'MAX_ENTRIES', 2):
            payload, _ = self.start()
            task = self.wait(payload['task']['id'])
        children = [n for n in task['tree'] if n['parent'] == str(self.directory)]
        self.assertEqual(len(children), 2)
        self.assertTrue(all(not n['complete'] for n in children))
        self.assertTrue(all(n['bytes'] == 0 for n in children))
        self.assertFalse(next(n for n in task['tree'] if n['parent'] is None)['complete'])

    def test_extended_mode_uses_larger_budget_and_binds_request(self):
        for i in range(4):
            (self.directory / str(i)).write_bytes(b'abc')
        with patch.object(sizes, 'MAX_ENTRIES', 1):
            payload, status = self.call('start', path=str(self.directory), request_id='extended', scan_mode='extended')
            self.ids.append(payload['task']['id'])
            task = self.wait(payload['task']['id'])
        self.assertEqual(task['status'], 'succeeded')
        self.assertEqual(task['files'], 4)
        self.assertEqual(self.call('start', path=str(self.directory), request_id='extended', scan_mode='standard')[1], 409)
        self.assertEqual(self.call('start', path=str(self.directory), request_id='bad-mode', scan_mode='invalid')[1], 400)

    def test_invalid_paths_and_linked_ancestors_rejected(self):
        for path in ('relative', '//server/share', '\\\\server\\share'):
            self.assertEqual(self.call('start', path=path, request_id='invalid')[1], 400)
        with patch.object(Path, 'is_junction', return_value=True):
            self.assertEqual(self.start()[1], 400)
        with patch.object(sizes.psutil, 'disk_partitions', return_value=[]):
            self.assertEqual(self.start()[1], 400)
        self.assertEqual(self.call('get', id=[])[1], 404)


if __name__ == '__main__':
    unittest.main()
