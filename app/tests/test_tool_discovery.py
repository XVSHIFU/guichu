import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from package_inventory import collect_packages
from tool_identity import enrich
from snapshot_state import reconcile
from assistant_tools import execute_tool


class DiscoveryTests(unittest.TestCase):
    def test_desktop_agent_helper_and_unknown_are_distinct(self):
        objects = [{'id': str(i), 'kind': 'software', 'name': name, 'path': 'D:\\Apps\\dsh\\' + name + '.exe', 'portable': True}
                   for i, name in enumerate(['DeepSeek Harness', 'Uninstall DeepSeek Harness', 'AI Notes'])]
        data = enrich({'objects': objects, 'relations': []})
        self.assertEqual(objects[0]['capabilities'], ['software', 'agent'])
        self.assertEqual(objects[0]['installDrive'], 'D:')
        self.assertEqual(objects[1]['entryRole'], 'auxiliary')
        self.assertEqual(objects[1]['capabilities'], ['software'])
        self.assertEqual(objects[2]['agentIdentity'], 'unknown')
        self.assertEqual(data['relations'], [])  # Ambiguous parent, do not invent ownership.
        result = execute_tool('search_objects', {'query': 'agent', 'cursor': ''}, objects, [], ['0', '1', '2'])
        self.assertEqual([o['id'] for o in result['objects']], ['0'])

    def test_helper_has_single_parent_and_enrichment_is_idempotent(self):
        data = {'objects': [{'id': str(i), 'kind': 'software', 'name': name, 'path': 'D:\\dsh\\' + name + '.exe', 'portable': True}
                           for i, name in enumerate(['DeepSeek Harness', 'Uninstall DeepSeek Harness'])], 'relations': []}
        enrich(data); enrich(data)
        self.assertEqual(data['relations'], [{'from': '0', 'to': '1', 'label': '软件附属程序'}])

    def test_configuration_disk_is_not_installation_disk(self):
        data = enrich({'objects': [{'id': 'a', 'kind': 'agent', 'name': 'Codex', 'path': 'C:\\Users\\user\\.codex', 'executable': 'D:\\bin\\codex.cmd'},
                                  {'id': 'b', 'kind': 'agent', 'name': 'Claude Code', 'path': 'C:\\Users\\user\\.claude'}], 'relations': []})
        self.assertEqual([o['installDrive'] for o in data['objects']], ['D:', '位置待确认'])

    def test_npm_scoped_commands_libraries_and_environment_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            roots = [Path(tmp)/'one', Path(tmp)/'two']
            for root in roots:
                package = root/'@deepseek-ai'/'dsh'; package.mkdir(parents=True)
                (package/'package.json').write_text(json.dumps({'name': '@deepseek-ai/dsh', 'version': '1', 'bin': {'dsh': 'cli.js'}}))
                lib = root/'library'; lib.mkdir(); (lib/'package.json').write_text('{"name":"library"}')
            result = enrich(collect_packages(locations=[('npm', root) for root in roots]))
            self.assertEqual(len(result['objects']), 2)
            self.assertEqual(len({o['id'] for o in result['objects']}), 2)
            self.assertTrue(all('agent' in o['capabilities'] and '本地网页' in o['interfaces'] for o in result['objects']))
            self.assertFalse(result['issues'])

    def test_pip_reads_entry_points_without_importing_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('tool', 'library'):
                info = root/(name + '-1.dist-info'); info.mkdir()
                (info/'METADATA').write_text('Name: '+name+'\nVersion: 1\n')
            (root/'tool-1.dist-info'/'entry_points.txt').write_text('[console_scripts]\nhello = missing.module:main\n')
            (root/'tool-1.dist-info'/'INSTALLER').write_text('uv\n')
            result = collect_packages(locations=[('pip', root)])
            self.assertEqual([o['name'] for o in result['objects']], ['tool'])
            self.assertEqual(result['objects'][0]['commands'], ['hello'])
            self.assertEqual(result['objects'][0]['packageInstaller'], 'uv')
            self.assertFalse(result['issues'])

    def test_invalid_and_limited_source_retains_previous_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); package = root/'tool'; package.mkdir()
            manifest = package/'package.json'
            manifest.write_text('{"name":"tool","bin":"main.js"}')
            previous = collect_packages(locations=[('npm', root)])
            manifest.write_text('{')
            current = collect_packages(locations=[('npm', root)])
            self.assertEqual(current['sources'][0]['status'], 'partial')
            self.assertTrue(reconcile(previous, current)['objects'][0]['stale'])
            with patch('package_inventory.MAX_ENTRIES', 0):
                current = collect_packages(locations=[('npm', root)])
            self.assertEqual(current['sources'][0]['status'], 'partial')

    def test_same_prefix_links_configuration_without_merging_other_environment(self):
        data = {'objects': [
            {'id': 'a', 'kind': 'agent', 'name': 'pi', 'executable': 'D:\\npm\\pi.cmd'},
            {'id': 'b', 'kind': 'software', 'name': '@earendil-works/pi-coding-agent', 'packageName': '@earendil-works/pi-coding-agent', 'distribution': 'npm', 'installPath': 'D:\\npm\\node_modules', 'commands': ['pi']},
            {'id': 'c', 'kind': 'software', 'name': '@earendil-works/pi-coding-agent', 'packageName': '@earendil-works/pi-coding-agent', 'distribution': 'npm', 'installPath': 'E:\\npm\\node_modules', 'commands': ['pi']}], 'relations': []}
        enrich(data)
        self.assertEqual(data['objects'][0]['installationId'], 'b')
        self.assertIn({'from':'b','to':'a','label':'配置与能力'},data['relations'])
        self.assertIn({'from':'b','to':'c','label':'同一产品的其他安装'},data['relations'])
        self.assertNotIn('installationId',data['objects'][2])

    def test_broken_package_does_not_keep_deleted_sibling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('broken', 'removed'):
                package = root/name; package.mkdir()
                (package/'package.json').write_text(json.dumps({'name': name, 'bin': 'main.js'}))
            old = collect_packages(locations=[('npm', root)])
            (root/'broken'/'package.json').write_text('{')
            (root/'removed'/'package.json').unlink()
            new = reconcile(old, collect_packages(locations=[('npm', root)]))
            self.assertEqual([o['name'] for o in new['objects']], ['broken'])
            self.assertTrue(new['objects'][0]['stale'])


if __name__ == '__main__': unittest.main()
