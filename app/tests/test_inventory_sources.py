from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import inventory
from snapshot_state import reconcile


class InventorySourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.codex = self.home / '.codex' / 'config.toml'
        self.codex.parent.mkdir()
        self.codex.write_text('[mcp_servers.fixture]\nurl="https://invalid.example/mcp"\n')
        self.claude = self.home / '.claude.json'
        self.claude.write_text('{"mcpServers":{"other":{"url":"https://invalid.example/other"}}}')
        self.skill = self.home / '.agents' / 'skills' / 'fixture' / 'SKILL.md'
        self.skill.parent.mkdir(parents=True)
        self.skill.write_text('---\nname: fixture\ndescription: fixture skill\n---\n')
        self.patches = ExitStack()
        self.patches.enter_context(patch.object(inventory, 'HOME', self.home))
        self.patches.enter_context(patch.object(inventory.psutil, 'process_iter', return_value=[]))
        self.patches.enter_context(patch.object(inventory.psutil, 'disk_partitions', return_value=[]))
        self.patches.enter_context(patch.object(inventory.shutil, 'which', return_value=None))
        self.patches.enter_context(patch.object(inventory, 'enrich_icons'))
        # Do not inspect real registry records or the hardcoded CCSwitch folder.
        self.patches.enter_context(patch.object(Path, 'glob', return_value=iter(())))
        def absent(*args):
            raise FileNotFoundError()
        fake_registry = SimpleNamespace(HKEY_LOCAL_MACHINE=1, HKEY_CURRENT_USER=2,
                                        KEY_WOW64_64KEY=4, KEY_WOW64_32KEY=8, KEY_READ=16, OpenKey=absent)
        self.patches.enter_context(patch.dict(sys.modules, {'winreg': fake_registry}))

    def tearDown(self):
        self.patches.close()
        self.temp.cleanup()

    def test_skill_labels_do_not_replace_source_group_for_skills_or_mcps(self):
        result = inventory.collect()
        source_ids = {source['id'] for source in result['sources']}
        self.assertTrue(all(obj['sourceKey'] in source_ids for obj in result['objects']))
        managed = [obj for obj in result['objects'] if obj['kind'] in ('skill', 'mcp')]
        self.assertEqual(len(managed), 3)
        self.assertTrue(all(obj['sourceKey'] == 'agent-config' for obj in managed))
        skill = next(obj for obj in managed if obj['kind'] == 'skill')
        self.assertEqual((skill['scope'], skill['source']), ('共享技能', '共享技能'))
        self.assertEqual(next(s for s in result['sources'] if s['id'] == 'agent-config')['status'], 'success')

    def test_config_and_skill_failures_propagate_to_reconciliation(self):
        previous = inventory.collect()
        managed_ids = {obj['id'] for obj in previous['objects'] if obj['kind'] in ('skill', 'mcp')}
        previous['objects'].append({'id': 'removed-software', 'kind': 'software', 'sourceKey': 'software-registry'})
        self.codex.write_text('[broken')
        self.claude.write_text('{broken')
        self.skill.write_text('---\nname: [broken\n---\n')
        current = inventory.collect()
        self.assertEqual(len(current['issues']), 3)
        self.assertTrue(all(issue['sourceKey'] == 'agent-config' for issue in current['issues']))
        statuses = {source['id']: source['status'] for source in current['sources']}
        self.assertEqual(statuses['agent-config'], 'partial')
        self.assertEqual(statuses['software-registry'], 'success')
        merged = reconcile(previous, current)
        retained = {obj['id']: obj for obj in merged['objects']}
        for oid in managed_ids:
            self.assertTrue(retained[oid]['stale'])
            self.assertEqual(retained[oid]['status'], '检查失败')
            self.assertEqual(retained[oid]['checkedAt'], next(obj['checkedAt'] for obj in previous['objects'] if obj['id'] == oid))
        self.assertNotIn('removed-software', retained)
        self.assertTrue(all(edge in merged['relations'] for edge in previous['relations']))

    def test_legacy_wrong_source_labels_retained_on_first_failed_rescan(self):
        previous = inventory.collect()
        legacy = {}
        for obj in previous['objects']:
            if obj['kind'] in ('skill', 'mcp'):
                obj['sourceKey'] = '共享技能' if obj['kind'] == 'skill' else 'pi 用户技能'
                legacy[obj['id']] = obj['sourceKey']
        # Unknown groups on unrelated kinds must not be normalized by this fix.
        previous['objects'].append({'id': 'unrelated', 'kind': 'software', 'sourceKey': 'custom-source'})
        self.codex.write_text('[broken')
        self.claude.write_text('{broken')
        self.skill.write_text('---\nname: [broken\n---\n')
        merged = reconcile(previous, inventory.collect())
        retained = {obj['id']: obj for obj in merged['objects']}
        for oid in legacy:
            self.assertEqual(retained[oid]['sourceKey'], 'agent-config')
            self.assertTrue(retained[oid]['stale'])
        self.assertNotIn('unrelated', retained)
        # Compatibility is applied to the returned snapshot, not the old record.
        self.assertEqual({obj['id']: obj['sourceKey'] for obj in previous['objects'] if obj['id'] in legacy}, legacy)


if __name__ == '__main__':
    unittest.main()
