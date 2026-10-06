from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import inventory
from assistant_tools import execute_tool
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
        self.assertTrue(all(obj['sourceKey'].startswith('agent-config') for obj in managed))
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
            self.assertTrue(retained[oid]['sourceKey'].startswith('agent-config'))
            self.assertTrue(retained[oid]['stale'])
        self.assertNotIn('unrelated', retained)
        # Compatibility is applied to the returned snapshot, not the old record.
        self.assertEqual({obj['id']: obj['sourceKey'] for obj in previous['objects'] if obj['id'] in legacy}, legacy)

    def test_one_failed_config_does_not_hide_other_config_removal(self):
        previous = inventory.collect()
        # Exercise migration from the old grouped snapshots as well.
        for obj in previous['objects']:
            if obj['kind'] == 'mcp':obj['sourceKey'] = 'agent-config'
        self.codex.write_text('[broken')
        self.claude.write_text('{"mcpServers":{}}')
        merged = reconcile(previous, inventory.collect())
        mcps = [o for o in merged['objects'] if o['kind'] == 'mcp']
        self.assertEqual([o['name'] for o in mcps], ['fixture'])
        self.assertTrue(mcps[0]['stale'])
        self.assertEqual(mcps[0]['sourceKey'], inventory.config_source(self.codex))

    def test_invalid_mcp_and_directory_command_are_not_valid_entries(self):
        self.claude.write_text(__import__('json').dumps({'mcpServers':{
            'directory':{'command':str(self.home)}, 'invalid':{'enabled':'false'}}}))
        result=inventory.collect()
        mcp=next(o for o in result['objects'] if o['name']=='directory')
        self.assertFalse(mcp['commandExists'])
        self.assertFalse(any(o['name']=='invalid' for o in result['objects']))
        self.assertEqual(next(s for s in result['sources'] if s['id']==inventory.config_source(self.claude))['status'],'partial')

    def test_process_read_failure_is_unknown_not_zero(self):
        with patch.object(inventory.psutil, 'process_iter', side_effect=inventory.psutil.AccessDenied()):
            result=inventory.collect()
        agent=next(o for o in result['objects'] if o['kind']=='agent')
        self.assertIsNone(agent['processCount'])
        self.assertEqual(next(s for s in result['sources'] if s['id']=='environment')['status'],'partial')

    def test_individual_unreadable_process_and_partial_positive_match(self):
        for names, expected in [([None],'unknown'), (['codex.exe',None],'matched'), ([], 'not_found')]:
            with patch.object(inventory.psutil,'process_iter',return_value=[SimpleNamespace(info={'name':name}) for name in names]):
                result=inventory.collect()
            agent=next(o for o in result['objects'] if o['name']=='Codex')
            tool=execute_tool('get_object',{'object_id':agent['id']},[agent],[],[agent['id']])
            self.assertEqual(tool['process']['state'],expected)
            self.assertEqual(tool['process']['observed_at'],agent['checkedAt'])
            if None in names:
                self.assertIsNone(tool['observations']['processCount'])
                self.assertEqual(tool['process']['coverage'],'partial')
                self.assertEqual(tool['process']['unreadable_count'],1)
            else:
                self.assertEqual(tool['observations']['processCount'],0)
                self.assertEqual(tool['process']['coverage'],'complete')

    def test_psutil_denied_attribute_becomes_unknown(self):
        # Exercise installed psutil's actual as_dict behavior, not just a guessed
        # exception at the process_iter boundary.
        process=inventory.psutil.Process()
        with patch.object(inventory.psutil.Process,'name',side_effect=inventory.psutil.AccessDenied()):
            info=process.as_dict(attrs=['name'],ad_value=None)
        self.assertIsNone(info['name'])
        with patch.object(inventory.psutil,'process_iter',return_value=[SimpleNamespace(info=info)]):
            result=inventory.collect()
        agent=next(o for o in result['objects'] if o['name']=='Codex')
        self.assertIsNone(agent['processCount'])
        self.assertEqual(agent['processObservation']['state'],'unknown')

    def test_process_iteration_failure_preserves_observed_match_as_lower_bound(self):
        def processes(*args,**kwargs):
            yield SimpleNamespace(info={'name':'codex.exe'})
            raise inventory.psutil.AccessDenied()
        with patch.object(inventory.psutil,'process_iter',side_effect=processes):result=inventory.collect()
        agent=next(o for o in result['objects'] if o['name']=='Codex')
        self.assertIsNone(agent['processCount'])
        self.assertEqual(agent['processObservation']['coverage'],'failed')
        self.assertEqual(agent['processObservation']['observed_matches'],1)

    def test_mixed_mcp_keeps_only_invalid_old_entry_not_known_removal(self):
        self.codex.write_text('[mcp_servers.valid]\nenabled=true\n[mcp_servers.invalid]\nenabled=true\n[mcp_servers.removed]\nenabled=true\n')
        previous=inventory.collect()
        self.codex.write_text('[mcp_servers.valid]\nenabled=false\n[mcp_servers.invalid]\nenabled="bad"\n')
        result=reconcile(previous,inventory.collect())
        mcps={o['name']:o for o in result['objects'] if o['kind']=='mcp'}
        self.assertFalse(mcps['valid']['enabled'])
        self.assertFalse(mcps['valid'].get('stale',False))
        self.assertTrue(mcps['invalid']['stale'])
        self.assertNotIn('removed',mcps)
        self.assertFalse(mcps['other'].get('stale',False))

    def test_claude_failure_does_not_retain_deleted_skill_or_plugin(self):
        self.codex.write_text('[plugins."fixture@market"]\nenabled=true\n')
        previous=inventory.collect()
        # The migration must isolate the first-batch snapshots too.
        for o in previous['objects']:
            if o['kind'] in ('skill','plugin'):o['sourceKey']='agent-config'
        self.codex.write_text('');self.skill.unlink();self.claude.write_text('{broken')
        result=reconcile(previous,inventory.collect())
        self.assertFalse(any(o['kind'] in ('skill','plugin') for o in result['objects']))

    def test_codex_failure_keeps_plugin_skills_and_marks_user_skill_enablement_unknown(self):
        self.codex.write_text('[plugins."fixture@market"]\nenabled=true\n')
        plugin_skill=self.home/'.codex/plugins/cache/market/fixture/v1/skills/child/SKILL.md'
        plugin_skill.parent.mkdir(parents=True);plugin_skill.write_text('---\nname: plugin-child\n---\n')
        previous=inventory.collect();self.codex.write_text('[broken')
        result=reconcile(previous,inventory.collect())
        self.assertTrue(next(o for o in result['objects'] if o['name']=='plugin-child')['stale'])
        self.assertTrue(next(o for o in result['objects'] if o['kind']=='plugin')['stale'])
        shared=next(o for o in result['objects'] if o['kind']=='skill' and o['source']=='共享技能')
        self.assertIsNone(shared['enabled'])
        self.assertIn('未知',shared['configurationStatus'])

    def test_bad_skill_root_does_not_retain_removed_other_root(self):
        other=self.home/'.claude/skills/other/SKILL.md';other.parent.mkdir(parents=True)
        other.write_text('---\nname: other-skill\n---\n')
        previous=inventory.collect();other.unlink();self.skill.write_text('---\nname: [bad\n---\n')
        result=reconcile(previous,inventory.collect())
        skills=[o for o in result['objects'] if o['kind']=='skill']
        self.assertEqual([o['name'] for o in skills],['fixture'])
        self.assertTrue(skills[0]['stale'])

    def test_legacy_plugin_skill_removed_despite_unrelated_failure(self):
        self.codex.write_text('[plugins."fixture@market"]\nenabled=true\n')
        child=self.home/'.codex/plugins/cache/market/fixture/v1/skills/child/SKILL.md'
        child.parent.mkdir(parents=True);child.write_text('---\nname: plugin-child\n---\n')
        previous=inventory.collect()
        for obj in previous['objects']:
            if obj['kind'] in ('skill','plugin'):
                obj['sourceKey']='agent-config';obj.pop('sourceDependencies',None)
        self.codex.write_text('');self.claude.write_text('{broken')
        result=reconcile(previous,inventory.collect())
        self.assertFalse(any(o['name']=='plugin-child' or o['kind']=='plugin' for o in result['objects']))


if __name__ == '__main__':
    unittest.main()
