from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import msi_action as msi


class MSIActionTests(unittest.TestCase):
    def setUp(self):
        self.obj = dict(id='software-fixture', name='Fixture MSI', kind='software', windowsInstaller=True,
                        registryHive='HKLM', registryView=256, registryKey='{12345678-1234-1234-1234-123456789ABC}')
        self.values = {'DisplayName': 'Fixture MSI', 'WindowsInstaller': 1, 'DisplayVersion': '1.0'}
        self.registry = MagicMock()
        self.registry.HKEY_LOCAL_MACHINE = 1
        self.registry.HKEY_CURRENT_USER = 2
        self.registry.KEY_READ = 8
        self.registry.QueryValueEx.side_effect = lambda key, name: (self.values[name], 1)
        self.registry_patch = patch.object(msi, 'winreg', self.registry)
        self.registry_patch.start()
        self.path_patch = patch.object(msi, '_installer_path', return_value='C:/Windows/System32/msiexec.exe')
        self.path_patch.start()

    def tearDown(self):
        self.registry_patch.stop()
        self.path_patch.stop()

    def test_launches_only_fixed_interactive_msi_arguments_after_revalidation(self):
        preview = msi.preview(self.obj)
        self.assertEqual(preview['usage_check'], 'installer')
        with patch.object(msi.subprocess, 'Popen', return_value=MagicMock(pid=123)) as launch:
            receipt = msi.apply(self.obj, preview['fingerprint'])
        args, kwargs = launch.call_args
        self.assertEqual(args[0], ['C:/Windows/System32/msiexec.exe', '/x', self.obj['registryKey']])
        self.assertFalse(kwargs['shell'])
        self.assertEqual(receipt['state'], 'waiting_user')
        self.assertEqual(receipt['pid'], 123)
        self.assertNotIn('UninstallString', [call.args[1] for call in self.registry.QueryValueEx.call_args_list])
        self.registry.OpenKey.assert_called_with(1, msi.UNINSTALL+'\\'+self.obj['registryKey'], 0, 8|256)

    def test_name_version_and_installer_changes_block_launch(self):
        preview = msi.preview(self.obj)
        for field, value in [('DisplayName', 'Another product'), ('DisplayVersion', '2.0'), ('WindowsInstaller', 0)]:
            original = self.values[field]
            self.values[field] = value
            with patch.object(msi.subprocess, 'Popen') as launch, self.assertRaises(ValueError):
                msi.apply(self.obj, preview['fingerprint'])
            launch.assert_not_called()
            self.values[field] = original

    def test_verify_registry_presence_not_process_launch_or_access_failure(self):
        self.assertEqual(msi.verify(self.obj)['state'], 'still_registered')
        self.registry.OpenKey.side_effect = FileNotFoundError()
        self.assertEqual(msi.verify(self.obj)['state'], 'removed')
        self.registry.OpenKey.side_effect = PermissionError()
        with self.assertRaises(PermissionError):
            msi.verify(self.obj)

    def test_rejects_untrusted_identity_without_reading_registry(self):
        for field, value in [('windowsInstaller', False), ('registryKey', 'evil.exe /quiet'), ('registryHive', 'HKCR'), ('registryView', 0), ('kind', 'directory')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                msi.preview(dict(self.obj, **{field: value}))
        self.registry.OpenKey.assert_not_called()


if __name__ == '__main__':
    unittest.main()
