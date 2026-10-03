from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scan_tasks as scans


class ScanTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'scans.sqlite'
        self.release = threading.Event()
        scans.initialize(self.connection)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def tearDown(self):
        self.release.set()
        self.wait()
        self.temp.cleanup()

    def wait(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = scans.status(self.connection)
            if not result['running']:
                return result
            time.sleep(.01)
        self.fail('scan did not finish')

    def test_success_and_partial_persist(self):
        self.assertEqual(scans.status(self.connection), {'running': False, 'error': None, 'task': None})
        for data, expected in [({'sources': [{'id': 'one', 'status': 'success'}], 'issues': []}, 'succeeded'),
                               ({'sources': [{'id': 'one', 'status': 'partial'}], 'issues': []}, 'partial'),
                               ({'sources': [], 'issues': [{'reason': 'fixture'}]}, 'partial')]:
            self.assertTrue(scans.start(self.connection, lambda: data))
            result = self.wait()
            self.assertEqual(result['task']['status'], expected)
            self.assertIsNotNone(result['task']['finished_at'])
            scans.initialize(self.connection)
            self.assertEqual(scans.status(self.connection), result)
        self.assertEqual(len(scans.list_tasks(self.connection)), 3)

    def test_concurrent_start_deduplicates_and_exposes_running_from_sqlite(self):
        entered = threading.Event()
        calls = []
        def work():
            calls.append(1)
            entered.set()
            self.release.wait(4)
            return {}
        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(lambda _: scans.start(self.connection, work), range(10)))
        self.assertEqual(sum(results), 1)
        self.assertTrue(entered.wait(2))
        result = scans.status(self.connection)
        self.assertTrue(result['running'])
        self.assertEqual(result['task']['status'], 'running')
        self.release.set()
        self.assertEqual(self.wait()['task']['status'], 'succeeded')
        self.assertEqual(calls, [1])

    def test_failure_is_safe_and_next_start_allowed(self):
        def fail():
            raise RuntimeError('SECRET_TOKEN fixture C:/private/config')
        self.assertTrue(scans.start(self.connection, fail))
        result = self.wait()
        self.assertEqual(result['task']['status'], 'failed')
        self.assertNotIn('SECRET_TOKEN', json.dumps(result))
        self.assertNotIn('private', json.dumps(result))
        self.assertTrue(scans.start(self.connection, lambda: {}))
        self.assertEqual(self.wait()['task']['status'], 'succeeded')

    def test_queued_is_durable_and_blocks_until_restart_interruption(self):
        with patch.object(scans.threading, 'Thread'):
            self.assertTrue(scans.start(self.connection, lambda: {}))
        self.assertEqual(scans.status(self.connection)['task']['status'], 'queued')
        self.assertFalse(scans.start(self.connection, lambda: {}))
        scans.initialize(self.connection)
        result = scans.status(self.connection)
        self.assertEqual(result['task']['status'], 'interrupted')
        scans.initialize(self.connection)
        self.assertEqual(scans.status(self.connection), result)

    def test_running_restart_and_latest_twenty(self):
        with self.connection() as db:
            for i in range(25):
                task = {'id': str(i), 'status': 'running' if i == 24 else 'succeeded', 'error': None}
                db.execute('INSERT INTO scan_tasks VALUES (?,?)', (str(i), json.dumps(task)))
        scans.initialize(self.connection)
        tasks = scans.list_tasks(self.connection)
        self.assertEqual(len(tasks), 20)
        self.assertEqual((tasks[0]['id'], tasks[-1]['id']), ('24', '5'))
        self.assertEqual(tasks[0]['status'], 'interrupted')

    def test_thread_start_failure_persists_failure(self):
        with patch.object(scans.threading, 'Thread') as thread:
            thread.return_value.start.side_effect = RuntimeError('fixture')
            self.assertFalse(scans.start(self.connection, lambda: {}))
        self.assertEqual(scans.status(self.connection)['task']['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
