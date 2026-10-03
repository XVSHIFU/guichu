from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import source_registry as registry


class SourceRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / 'registry.sqlite'
        self.directory = self.root / 'portable-fixture'
        self.directory.mkdir()
        (self.directory / 'keep.txt').write_text('keep')
        registry.initialize(self.connection)

    def tearDown(self):
        self.temp.cleanup()

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.database, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def call(self, route, **body):
        return registry.dispatch(self.connection, '/api/source/' + route, body)

    def add(self, **extra):
        return self.call('add', **dict({'type': 'portable', 'path': str(self.directory)}, **extra))

    def test_concurrent_duplicate_is_persistent_and_per_type(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.add(), range(8)))
        self.assertTrue(all(status == 200 for _, status in results))
        self.assertEqual(len({payload['source']['id'] for payload, _ in results}), 1)
        if os.name == 'nt':
            self.assertEqual(self.add(path=str(self.directory).upper())[0]['source']['id'], results[0][0]['source']['id'])
        registry.initialize(self.connection)
        self.assertEqual(len(registry.list_sources(self.connection)), 1)
        self.assertEqual(self.add(type='project', label='项目')[1], 200)
        self.assertEqual(len(self.call('list')[0]['sources']), 2)

    def test_remove_never_touches_directory_contents(self):
        source = self.add()[0]['source']
        self.assertEqual(self.call('remove', id=source['id'])[1], 200)
        self.assertEqual((self.directory / 'keep.txt').read_text(), 'keep')
        self.assertEqual(self.call('list')[0]['sources'], [])
        self.assertEqual(self.call('remove', id=source['id'])[1], 404)

    def test_paths_and_inputs_rejected(self):
        for value in ['relative/path', '//server/share', '\\\\server\\share', str(self.directory.anchor), str(self.directory / 'missing'), str(self.directory / 'keep.txt')]:
            with self.subTest(path=value):
                self.assertEqual(self.add(path=value)[1], 400)
        self.assertEqual(self.add(type=[])[1], 400)
        self.assertEqual(self.add(type='cloud')[1], 400)
        self.assertEqual(self.add(label='x'*81)[1], 400)
        self.assertEqual(self.add(label='line\nbreak')[1], 400)
        with patch.object(Path, 'is_symlink', return_value=True):
            self.assertEqual(self.add()[1], 400)
        if hasattr(Path, 'is_junction'):
            original = Path.is_junction
            with patch.object(Path, 'is_junction', lambda path: path == self.root or original(path)):
                self.assertEqual(self.add()[1], 400)

    def test_limit_allows_existing_registration_and_preserves_missing_source(self):
        first = self.add()[0]['source']
        for number in range(19):
            directory = self.root / str(number)
            directory.mkdir()
            self.assertEqual(self.add(path=str(directory))[1], 200)
        self.assertEqual(self.add()[1], 200)
        additional = self.root / 'additional'
        additional.mkdir()
        self.assertEqual(self.add(path=str(additional))[1], 409)
        (self.directory / 'keep.txt').unlink()
        self.directory.rmdir()
        self.assertEqual(len(self.call('list')[0]['sources']), 20)
        self.assertEqual(self.call('remove', id=first['id'])[1], 200)
        self.assertEqual(self.add(path=str(additional))[1], 200)


if __name__ == '__main__':
    unittest.main()
