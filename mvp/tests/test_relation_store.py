from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from relation_store import dispatch, initialize, overlay


class RelationStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'relations.sqlite'
        self.objects = [{'id': 'a'}, {'id': 'b'}]
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

    def call(self, command, **body):
        return dispatch(self.connection, '/api/relation/' + command, body, self.objects)

    def add(self):
        return self.call('add', from_id='a', to_id='b', label='使用')[0]['relation']

    def test_concurrent_add_is_idempotent_and_persists(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.add(), range(8)))
        self.assertEqual(len({item['id'] for item in results}), 1)
        initialize(self.connection)
        self.assertEqual(len(self.call('list')[0]['relations']), 1)
        self.assertEqual(self.call('add', from_id='a', to_id='b', label=' 使用 ')[0]['relation']['id'], results[0]['id'])

    def test_overlay_preserves_scanned_edge_and_removal_only_deletes_manual(self):
        relation = self.add()
        scanned = {'from': 'a', 'to': 'b', 'label': '使用'}
        data = {'objects': self.objects, 'relations': [scanned]}
        view = overlay(data, self.connection)
        self.assertEqual(view['relations'], [scanned])
        self.assertEqual(data['relations'], [scanned])
        self.assertEqual(self.call('remove', id=relation['id'])[1], 200)
        self.assertEqual(overlay(data, self.connection)['relations'], [scanned])
        self.assertEqual(self.call('remove', id='automatic-id')[1], 404)

    def test_missing_endpoint_retained_without_overlay_and_reappears(self):
        relation = self.add()
        self.objects = [{'id': 'a'}]
        self.assertTrue(self.call('list')[0]['relations'][0]['missing'])
        self.assertEqual(overlay({'objects': self.objects}, self.connection)['relations'], [])
        self.objects.append({'id': 'b'})
        view = overlay({'objects': self.objects}, self.connection)
        self.assertEqual(view['relations'][0]['id'], relation['id'])
        self.assertTrue(view['relations'][0]['manual'])
        self.assertEqual(overlay(view, self.connection), view)
        self.assertEqual(self.call('remove', id=relation['id'])[1], 200)
        self.assertEqual(overlay(view, self.connection)['relations'], [])

    def test_validation_and_no_snapshot(self):
        for body, status in [({'from_id': 'a', 'to_id': 'a', 'label': '自身'}, 400),
                             ({'from_id': 'a', 'to_id': 'missing', 'label': '使用'}, 404),
                             ({'from_id': 'a', 'to_id': 'b', 'label': ' '}, 400),
                             ({'from_id': 'a', 'to_id': 'b', 'label': '字' * 81}, 400),
                             ({'from_id': [], 'to_id': 'b', 'label': '使用'}, 400)]:
            self.assertEqual(self.call('add', **body)[1], status)
        self.assertIsNone(overlay(None, self.connection))


if __name__ == '__main__':
    unittest.main()
