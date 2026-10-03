import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from assistant_tools import execute_tool, tools_catalog


class AssistantToolsTests(unittest.TestCase):
    def setUp(self):
        self.objects = [{'id': 'a', 'name': 'Alpha', 'kind': 'mcp', 'source': '扫描',
                         'checkedAt': '2026-10-03', 'enabled': True, 'transport': 'HTTP',
                         'api_key': 'SECRET', 'env': {'TOKEN': 'SECRET'}, 'url': 'SECRET',
                         'command': 'SECRET', 'path': 'SECRET', 'description': 'SECRET'},
                        {'id': 'b', 'name': 'Beta', 'kind': 'skill', 'source': '扫描'},
                        {'id': 'c', 'name': 'Private', 'kind': 'skill'}]
        self.relations = [{'from': 'a', 'to': 'b', 'label': '使用', 'token': 'SECRET'},
                          {'from': 'a', 'to': 'c', 'label': '隐藏'}]

    def call(self, name, args, allowed=('a', 'b')):
        return execute_tool(name, args, self.objects, self.relations, allowed)

    def test_schema_and_argument_boundaries(self):
        self.assertEqual(len(tools_catalog()), 5)
        for tool in tools_catalog():
            self.assertFalse(tool['function']['parameters']['additionalProperties'])
        for name, args in [('shell', {}), ('get_object', {'object_id': 'a', 'path': '/'}),
                           ('search_objects', {'query': '', 'allowed_ids': ['c']}),
                           ('get_object', {'object_id': 'c'}), ('get_object', {})]:
            self.assertIn('error', self.call(name, args))
        self.assertEqual(self.call('search_objects', {'query': ''}, allowed=[])['objects'], [])

    def test_scope_evidence_and_secret_whitelist(self):
        found = self.call('search_objects', {'query': ''})
        self.assertEqual([obj['id'] for obj in found['objects']], ['a', 'b'])
        obj = self.call('get_object', {'object_id': 'a'})
        self.assertEqual(obj['evidence'], {'object_id': 'a', 'source': '扫描', 'checked_at': '2026-10-03'})
        summary = self.call('read_config_summary', {'object_id': 'a'})
        self.assertEqual(summary['summary'], {'enabled': True, 'transport': 'HTTP'})
        relation = self.call('get_relations', {'object_id': 'a'})
        self.assertEqual(len(relation['relations']), 1)
        self.assertNotIn('SECRET', json.dumps([found, obj, summary, relation]))

    def test_search_limit_and_utf8_budget(self):
        self.objects = [{'id': str(i), 'name': '长' * 500, 'kind': 'skill', 'source': '源' * 500}
                        for i in range(30)]
        result = self.call('search_objects', {'query': ''}, allowed=[str(i) for i in range(30)])
        self.assertLessEqual(len(result['objects']), 20)
        self.assertTrue(result['truncated'])
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode()), 32768)

    def test_directory_current_level_limit_no_contents(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            for i in range(105):
                (path / f'file{i}.txt').write_text('SECRET')
            self.objects.append({'id': 'd', 'name': 'Temp', 'kind': 'directory', 'path': str(path)})
            with patch.object(Path, 'read_text', side_effect=AssertionError('no content reads')):
                result = self.call('list_directory', {'object_id': 'd'}, allowed=['d'])
            self.assertEqual(len(result['entries']), 100)
            self.assertTrue(result['truncated'])
            self.assertNotIn('SECRET', json.dumps(result))
            self.assertNotIn(str(path), json.dumps(result))
            with patch.object(Path, 'is_junction', return_value=True):
                self.assertIn('error', self.call('list_directory', {'object_id': 'd'}, allowed=['d']))

    def test_directory_rejects_unc_wrong_kind_and_model_path(self):
        self.assertIn('error', self.call('list_directory', {'object_id': 'a'}))
        self.objects.append({'id': 'd', 'kind': 'directory', 'path': '//host/share'})
        self.assertIn('error', self.call('list_directory', {'object_id': 'd'}, allowed=['d']))
        self.assertIn('error', self.call('list_directory', {'object_id': 'd', 'path': 'C:/'}))


if __name__ == '__main__':
    unittest.main()
