import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import registered_sources as registered
from snapshot_state import reconcile


class RegisteredSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    def source(self, kind='portable', rid='one', root=None):
        return {'id': rid, 'type': kind, 'path': str(root or self.root), 'label': 'Fixture'}

    def collect(self, kind='portable'):
        return registered.collect_registered([self.source(kind)])

    def test_portable_only_root_and_one_child_no_execution_or_content_read(self):
        (self.root / 'top.EXE').write_bytes(b'not an executable')
        child = self.root / 'child'
        child.mkdir()
        (child / 'app.exe').write_bytes(b'fixture')
        deep = child / 'deep'
        deep.mkdir()
        (deep / 'hidden.exe').write_bytes(b'fixture')
        (self.root / 'readme.txt').write_text('fixture')
        with patch.object(Path, 'open', side_effect=AssertionError('no file content reads')):
            result = self.collect()
        apps = [obj for obj in result['objects'] if obj['kind'] == 'software']
        self.assertEqual({obj['name'] for obj in apps}, {'top', 'app'})
        self.assertTrue(all(obj['portable'] and obj['status'] == '入口已发现' for obj in apps))
        self.assertTrue(all(obj['_displayIcon'] == obj['path'] for obj in apps))
        self.assertEqual(len(result['relations']), 2)
        self.assertEqual(result['sources'][0]['status'], 'success')

    def test_limits_mark_partial(self):
        for i in range(5):
            (self.root / f'app{i}.exe').touch()
        for constant in ('MAX_ENTRIES', 'MAX_EXECUTABLES'):
            with patch.object(registered, constant, 2):
                result = self.collect()
            self.assertEqual(result['sources'][0]['status'], 'partial')
            self.assertEqual(len([obj for obj in result['objects'] if obj['kind'] == 'software']), 2)
            self.assertTrue(result['issues'])

    def test_project_allowlist_missing_files_and_no_nested_discovery(self):
        empty = self.collect('project')
        self.assertEqual(empty['sources'][0]['status'], 'success')
        self.assertFalse([obj for obj in empty['objects'] if obj['kind'] == 'mcp'])
        (self.root / '.codex').mkdir()
        (self.root / '.codex' / 'config.toml').write_text('[mcp_servers.local]\ncommand="node"\nargs=["SECRET"]\nenabled=false\n[mcp_servers.local.env]\nTOKEN="SECRET"\n')
        (self.root / '.mcp.json').write_text(json.dumps({'mcpServers': {'remote': {'url': 'https://secret.example/SECRET', 'headers': {'Authorization': 'SECRET'}}}}))
        nested = self.root / 'nested'
        nested.mkdir()
        (nested / '.mcp.json').write_text('{invalid nested configuration')
        result = self.collect('project')
        mcps = [obj for obj in result['objects'] if obj['kind'] == 'mcp']
        self.assertEqual({obj['name'] for obj in mcps}, {'local', 'remote'})
        self.assertTrue(all(obj['scope'] == 'project' for obj in mcps))
        self.assertFalse(next(obj for obj in mcps if obj['name'] == 'local')['enabled'])
        self.assertEqual(next(obj for obj in mcps if obj['name'] == 'remote')['transport'], 'HTTP')
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertFalse(result['issues'])

    def test_source_scoped_ids_and_independent_failure_retention(self):
        (self.root / '.mcp.json').write_text('{"mcpServers":{"fixture":{"command":"node"}}}')
        other = self.root / 'other'
        other.mkdir()
        (other / 'app.exe').touch()
        sources = [self.source('project'), self.source('portable', 'two', other)]
        previous = registered.collect_registered(sources)
        (self.root / '.mcp.json').write_text('{invalid')
        (other / 'app.exe').unlink()
        current = registered.collect_registered(sources)
        self.assertEqual({s['id']: s['status'] for s in current['sources']}, {'registered:one': 'partial', 'registered:two': 'success'})
        merged = reconcile(previous, current)
        self.assertTrue(next(obj for obj in merged['objects'] if obj['kind'] == 'mcp')['stale'])
        self.assertFalse(any(obj['kind'] == 'software' for obj in merged['objects']))
        duplicate = registered.collect_registered([self.source('project', 'one'), self.source('project', 'three')])
        ids = [obj['id'] for obj in duplicate['objects']]
        self.assertEqual(len(ids), len(set(ids)))

    def test_invalid_config_size_and_link_paths_fail_safely(self):
        (self.root / '.mcp.json').write_bytes(b' ' * (registered.MAX_CONFIG_BYTES + 1))
        self.assertEqual(self.collect('project')['sources'][0]['status'], 'partial')
        (self.root / '.mcp.json').write_text('{}')
        original = Path.is_junction
        with patch.object(Path, 'is_junction', lambda path: path.name == '.mcp.json' or original(path)):
            self.assertEqual(self.collect('project')['sources'][0]['status'], 'partial')
        for raw in ('relative', '//host/share'):
            result = registered.collect_registered([{**self.source(), 'path': raw}])
            self.assertFalse(result['objects'])
            self.assertEqual(result['sources'][0]['status'], 'partial')
        linked = self.root / 'linked'
        linked.mkdir()
        (linked / 'ignored.exe').touch()
        with patch.object(Path, 'is_junction', lambda path: path == linked or original(path)):
            result = self.collect()
        self.assertFalse(any(obj['kind'] == 'software' for obj in result['objects']))
        self.assertEqual(result['sources'][0]['status'], 'partial')

    def test_project_mcp_limit_shared_across_files_and_long_names_rejected(self):
        (self.root / '.codex').mkdir()
        (self.root / '.codex' / 'config.toml').write_text('[mcp_servers.first]\ncommand="node"\n')
        (self.root / '.mcp.json').write_text(json.dumps({'mcpServers': {
            'second': {'command': 'node'}, 'third': {'command': 'node'}}}))
        with patch.object(registered, 'MAX_MCPS', 2):
            result = self.collect('project')
        self.assertEqual(len([obj for obj in result['objects'] if obj['kind'] == 'mcp']), 2)
        self.assertEqual(result['sources'][0]['status'], 'partial')
        (self.root / '.mcp.json').write_text(json.dumps({'mcpServers': {'x' * 257: {'command': 'node'}}}))
        result = self.collect('project')
        self.assertEqual(result['sources'][0]['status'], 'partial')
        self.assertTrue(all(len(obj['name']) <= 256 for obj in result['objects']))


if __name__ == '__main__':
    unittest.main()
