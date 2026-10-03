from pathlib import Path
import os
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mcp_config_action as action


class MCPConfigActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'config.toml'
        self.backups = Path(self.temp.name) / 'backups'

    def tearDown(self):
        self.temp.cleanup()

    def write(self, text):
        self.path.write_bytes(text.encode())
        return self.path.read_bytes()

    def apply(self, enabled=False):
        preview = action.preview(self.path, 'sample', enabled)
        self.assertNotIn('after_bytes', preview)
        return action.apply(self.path, 'sample', enabled, preview['before_hash'], self.backups)

    def test_exact_boolean_edit_preserves_comments_nested_env_and_crlf(self):
        original = self.write('# config\r\n[mcp_servers.sample]\r\ncommand = "test"\r\n  enabled = true  # keep\r\n[mcp_servers.sample.env]\r\nTOKEN = "secret-fixture"\r\n')
        receipt = self.apply()
        self.assertEqual(self.path.read_bytes(), original.replace(b'enabled = true', b'enabled = false'))
        self.assertEqual(Path(receipt['backup_path']).read_bytes(), original)
        self.assertTrue(action.restore(self.path, receipt)['restored'])
        self.assertEqual(self.path.read_bytes(), original)

    def test_missing_key_inserted_in_parent_table(self):
        original = self.write('[mcp_servers.sample]\ncommand="test"\n[mcp_servers.sample.env]\nX="keep"\n')
        receipt = self.apply()
        config = tomllib.loads(self.path.read_text())
        self.assertFalse(config['mcp_servers']['sample']['enabled'])
        self.assertEqual(config['mcp_servers']['sample']['env'], {'X': 'keep'})
        self.assertEqual(self.path.read_bytes().replace(b'enabled = false\n', b''), original)
        self.assertIsNone(receipt['before_enabled'])

    def test_apply_conflict_and_restore_conflict(self):
        self.write('[mcp_servers.sample]\nenabled=true\n')
        preview = action.preview(self.path, 'sample', False)
        self.path.write_bytes(self.path.read_bytes() + b'# external edit\n')
        with self.assertRaises(ValueError):
            action.apply(self.path, 'sample', False, preview['before_hash'], self.backups)
        self.assertFalse(self.backups.exists())
        receipt = self.apply()
        self.path.write_bytes(self.path.read_bytes() + b'# newer edit\n')
        changed = self.path.read_bytes()
        with self.assertRaises(ValueError):
            action.restore(self.path, receipt)
        self.assertEqual(self.path.read_bytes(), changed)

    def test_replace_failure_keeps_original_and_verified_backup(self):
        original = self.write('[mcp_servers.sample]\nenabled=true\n')
        with patch.object(action.os, 'replace', side_effect=PermissionError('fixture')):
            with self.assertRaises(PermissionError) as failure:
                self.apply()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(Path(failure.exception.receipt['backup_path']).read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob('.mcp-config-*.tmp')), [])

    def test_backup_write_failure_does_not_replace(self):
        self.write('[mcp_servers.sample]\nenabled=true\n')
        with patch.object(action.os, 'fsync', side_effect=OSError('fixture')), patch.object(action.os, 'replace') as replace:
            with self.assertRaises(OSError):
                self.apply()
            replace.assert_not_called()

    def test_reject_ambiguous_duplicate_large_link_and_nonfile(self):
        for text in ('[mcp_servers.sample]\nenabled=true\nenabled=false\n',
                     'mcp_servers.sample.enabled=true\n',
                     '[mcp_servers.sample]\n"enabled"=true\n',
                     '[mcp_servers.sample]\nenabled="true"\n',
                     '[mcp_servers.sample]\ncommand="""multiline"""\n'):
            self.write(text)
            with self.assertRaises(ValueError):
                action.preview(self.path, 'sample', False)
        self.path.write_bytes(b' ' * (action.MAX_BYTES + 1))
        with self.assertRaises(ValueError):
            action.preview(self.path, 'sample', False)
        with self.assertRaises(ValueError):
            action.preview(self.path.parent, 'sample', False)
        with patch.object(Path, 'is_junction', return_value=True):
            with self.assertRaises(ValueError):
                action.preview(self.path, 'sample', False)

    def test_backup_tampering_and_wrong_target_rejected(self):
        self.write('[mcp_servers.sample]\nenabled=true\n')
        receipt = self.apply()
        other = self.path.parent / 'other.toml'
        other.write_bytes(self.path.read_bytes())
        with self.assertRaises(ValueError):
            action.restore(other, receipt)
        Path(receipt['backup_path']).write_bytes(b'tampered=true\n')
        with self.assertRaises(ValueError):
            action.restore(self.path, receipt)

    def test_backup_callback_runs_before_replace_and_failure_keeps_original(self):
        original = self.write('[mcp_servers.sample]\nenabled=true\n')
        preview = action.preview(self.path, 'sample', False)
        records = []
        def persist(receipt):
            self.assertEqual(self.path.read_bytes(), original)
            self.assertEqual(Path(receipt['backup_path']).read_bytes(), original)
            records.append(receipt)
            raise RuntimeError('database unavailable')
        with patch.object(action.os, 'replace') as replace:
            with self.assertRaises(RuntimeError):
                action.apply(self.path, 'sample', False, preview['before_hash'], self.backups, on_backup=persist)
            replace.assert_not_called()
        self.assertEqual(len(records), 1)
        self.assertEqual(self.path.read_bytes(), original)
        accepted = []
        action.apply(self.path, 'sample', False, preview['before_hash'], self.backups,
                     on_backup=lambda receipt: accepted.append((receipt, self.path.read_bytes())))
        self.assertEqual(accepted[0][1], original)
        self.assertNotEqual(self.path.read_bytes(), original)

    @unittest.skipUnless(os.name == 'nt', 'Windows DACL test')
    def test_windows_dacl_preserved_apply_restore_backup_private(self):
        self.write('[mcp_servers.sample]\nenabled=true\n')
        # Explicit protected DACL with an additional read-only Everyone ACE.
        custom = action._private_dacl() + '(A;;FR;;;WD)'
        action._set_dacl(self.path, custom)
        original = action._dacl(self.path)
        receipt = self.apply()
        self.assertEqual(action._dacl(self.path), original)
        backup_dacl = action._dacl(receipt['backup_path'])
        self.assertEqual(backup_dacl.replace('D:PAI', 'D:P', 1), action._private_dacl())
        self.assertNotIn(';;;WD)', backup_dacl)
        self.assertNotIn(';;;BU)', backup_dacl)
        action.restore(self.path, receipt)
        self.assertEqual(action._dacl(self.path), original)

    @unittest.skipUnless(os.name == 'nt', 'Windows DACL test')
    def test_windows_permission_failures_never_replace(self):
        original = self.write('[mcp_servers.sample]\nenabled=true\n')
        real_set = action._set_dacl
        def fail_temporary(path, sddl):
            if str(path).endswith('.tmp'):
                raise PermissionError('DACL fixture')
            return real_set(path, sddl)
        for setter in (lambda *args: (_ for _ in ()).throw(PermissionError('backup DACL fixture')), fail_temporary):
            with patch.object(action, '_set_dacl', side_effect=setter), patch.object(action.os, 'replace') as replace:
                with self.assertRaises(PermissionError):
                    self.apply()
                replace.assert_not_called()
            self.assertEqual(self.path.read_bytes(), original)
        receipt = self.apply()
        after = self.path.read_bytes()
        with patch.object(action, '_set_dacl', side_effect=PermissionError('restore DACL fixture')), patch.object(action.os, 'replace') as replace:
            with self.assertRaises(PermissionError):
                action.restore(self.path, receipt)
            replace.assert_not_called()
        self.assertEqual(self.path.read_bytes(), after)


if __name__ == '__main__':
    unittest.main()
