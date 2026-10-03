import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import recycle_action as recycle


class RecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='recycle-adapter-test-')
        self.base = Path(self.temp.name).resolve()
        self.target = self.base / 'target'
        self.target.mkdir()
        (self.target / 'fixture.txt').write_bytes(b'fixture')
        self.processes = patch.object(recycle.psutil, 'process_iter', return_value=[])
        self.processes.start()

    def tearDown(self):
        self.processes.stop()
        self.temp.cleanup()

    def test_preview_metadata_only_and_fingerprint_change(self):
        (self.target / 'child').mkdir()
        (self.target / 'child' / 'empty').touch()
        with patch.object(Path, 'open', side_effect=AssertionError('no content reads')):
            before = recycle.preview(self.target)
        self.assertEqual((before['files'], before['directories'], before['bytes']), (2, 2, 7))
        self.assertEqual(before['usage_check'], 'complete')
        self.assertEqual(len(before['fingerprint']), 64)
        self.assertIn('手动恢复', before['restore_note'])
        (self.target / 'fixture.txt').write_bytes(b'changed fixture')
        self.assertNotEqual(recycle.preview(self.target)['fingerprint'], before['fingerprint'])

    def test_conflict_does_not_call_recycle(self):
        before = recycle.preview(self.target)
        (self.target / 'new').touch()
        with patch.object(recycle, '_recycle') as provider:
            with self.assertRaises(ValueError):
                recycle.apply(self.target, before['fingerprint'])
            provider.assert_not_called()

    def test_mock_success_requires_disappearance_and_api_success(self):
        before = recycle.preview(self.target)
        with patch.object(recycle, '_recycle', return_value=True):
            with self.assertRaises(ValueError):
                recycle.apply(self.target, before['fingerprint'])
        def mock_move(path):
            self.assertTrue(path.resolve().is_relative_to(self.base))
            path.rename(self.base / 'mock-recycled')
            return True
        with patch.object(recycle, '_recycle', side_effect=mock_move):
            receipt = recycle.apply(self.target, before['fingerprint'])
        self.assertEqual(receipt['state'], 'recycled')
        self.assertTrue((self.base / 'mock-recycled' / 'fixture.txt').is_file())

    def test_api_failure_keeps_original_no_fallback(self):
        before = recycle.preview(self.target)
        with patch.object(recycle, '_recycle', side_effect=OSError('fixture')) as provider:
            with self.assertRaises(ValueError) as raised:
                recycle.apply(self.target, before['fingerprint'])
            self.assertEqual(provider.call_count, 1)
        self.assertEqual(raised.exception.receipt['state'], 'failed')
        self.assertTrue(self.target.is_dir())

    def test_protected_paths_roots_and_ancestors(self):
        for path in (Path(self.target.anchor), Path.home(), 'relative', '//server/share'):
            with self.assertRaises(ValueError):
                recycle.preview(path)
        for protected in (self.base, self.target, self.target / 'fixture.txt'):
            with self.assertRaises(ValueError):
                recycle.preview(self.target, [protected])
        with patch.dict(os.environ, {'ProgramData': str(self.base)}):
            with self.assertRaises(ValueError):
                recycle.preview(self.target)
        # HOME children remain eligible; only HOME itself and ancestors are denied.
        with patch.object(Path, 'home', return_value=self.base):
            self.assertEqual(recycle.preview(self.target)['path'], str(self.target))

    def test_links_permissions_and_limits_are_hard_failures(self):
        original = recycle._is_link
        with patch.object(recycle, '_is_link', side_effect=lambda path, metadata=None: path.name == 'fixture.txt' or original(path, metadata)):
            with self.assertRaises(ValueError):
                recycle.preview(self.target)
        with patch.object(recycle.os, 'scandir', side_effect=PermissionError('fixture')):
            with self.assertRaises(ValueError):
                recycle.preview(self.target)
        for constant in ('MAX_ENTRIES', 'MAX_SECONDS'):
            with patch.object(recycle, constant, 0):
                with self.assertRaises(ValueError):
                    recycle.preview(self.target)

    def test_matching_process_refused_and_access_denied_marked_partial(self):
        process = SimpleNamespace(pid=123, exe=lambda: str(self.target / 'app.exe'), cwd=lambda: str(self.base))
        with patch.object(recycle.psutil, 'process_iter', return_value=[process]):
            with self.assertRaises(ValueError) as raised:
                recycle.preview(self.target)
        self.assertEqual(raised.exception.processes[0]['pid'], 123)
        def denied():
            raise recycle.psutil.AccessDenied(123)
        process.exe = denied
        with patch.object(recycle.psutil, 'process_iter', return_value=[process]):
            self.assertEqual(recycle.preview(self.target)['usage_check'], 'partial')

    @unittest.skipUnless(os.name == 'nt', 'Windows COM provider contract')
    def test_dedicated_recycle_interface_requires_success_and_new_item(self):
        from unittest.mock import Mock
        from win32com.shell import shell
        transfer = Mock()
        transfer.RecycleItem.return_value = (0, object())
        parent = Mock()
        parent.BindToHandler.return_value = transfer
        item, destination = object(), object()
        with patch.object(shell, 'SHCreateItemFromParsingName', side_effect=lambda name, *args:
                          destination if name == 'shell:RecycleBinFolder' else
                          parent if name == str(self.target.parent) else item):
            self.assertTrue(recycle._recycle(self.target))
            transfer.RecycleItem.assert_called_once_with(item, destination, 0)
            transfer.RemoveItem.assert_not_called()
            for result in ((0, None), (-1, object()), (0x80004005, object())):
                transfer.RecycleItem.return_value = result
                with self.assertRaises(ValueError):
                    recycle._recycle(self.target)
            transfer.RecycleItem.side_effect = RuntimeError('fixture')
            with self.assertRaises(ValueError):
                recycle._recycle(self.target)
            transfer.RemoveItem.assert_not_called()
        self.assertTrue(self.target.exists())


if __name__ == '__main__':
    unittest.main()
