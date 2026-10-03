from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import directory_browser as browser


class DirectoryBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name).resolve()
        self.mounts = patch.object(browser.psutil, 'disk_partitions', return_value=[
            SimpleNamespace(mountpoint=str(self.path.anchor), opts='rw')])
        self.mounts.start()
        browser._snapshots.clear()
        for i in range(310):
            (self.path / f'item-{i:04}.txt').touch()

    def tearDown(self):
        self.mounts.stop()
        browser._snapshots.clear()
        self.temp.cleanup()

    def browse(self, **kwargs):
        return browser.browse_directory({'path': str(self.path), **kwargs})

    def test_mutation_does_not_shift_pages_and_refresh_sees_changes(self):
        first, status = self.browse()
        self.assertEqual(status, 200)
        (self.path / 'item-0000.txt').unlink()
        (self.path / 'a-new.txt').touch()
        names = [e['name'] for e in first['entries']]
        cursor = first['next']
        with patch.object(browser.os, 'scandir', side_effect=AssertionError('must use snapshot')):
            while cursor:
                page, status = self.browse(cursor=cursor)
                self.assertEqual(status, 200)
                names.extend(e['name'] for e in page['entries'])
                cursor = page['next']
        self.assertEqual(names, [f'item-{i:04}.txt' for i in range(310)])
        fresh, _ = self.browse()
        self.assertEqual(fresh['entries'][0]['name'], 'a-new.txt')

    def test_expired_cursor_restarts_with_fresh_first_page(self):
        with patch.object(browser.time, 'monotonic', return_value=100):
            first, _ = self.browse()
        with patch.object(browser.time, 'monotonic', return_value=100 + browser.SNAPSHOT_TTL):
            payload, status = self.browse(cursor=first['next'])
            self.assertEqual((status, payload['code']), (409, 'cursor_expired'))
            self.assertEqual(self.browse()[1], 200)

    def test_cursor_binding_restart_and_legacy_offset(self):
        first, _ = self.browse(offset=0)
        self.assertEqual(self.browse(cursor=first['next'], query='item')[1], 409)
        self.assertEqual(self.browse(offset=150)[1], 409)
        browser._snapshots.clear()
        self.assertEqual(self.browse(cursor=first['next'])[1], 409)

    def test_cache_is_bounded_and_evicts_oldest(self):
        with patch.object(browser, 'MAX_SNAPSHOTS', 2):
            first, _ = self.browse()
            self.browse()
            self.browse()
            self.assertEqual(len(browser._snapshots), 2)
            self.assertEqual(self.browse(cursor=first['next'])[1], 409)

    def test_nonlocal_path_rejected(self):
        for path in ('relative', '//server/share', '\\\\server\\share'):
            self.assertEqual(browser.browse_directory({'path': path})[1], 400)

    def test_malformed_cursor_and_link_target_rejected(self):
        for cursor in ('不是游标', [], 'unknown'):
            self.assertEqual(self.browse(cursor=cursor)[1], 409)
        with patch.object(Path, 'is_junction', return_value=True), patch.object(browser.os, 'scandir') as scan:
            self.assertEqual(self.browse()[1], 403)
            scan.assert_not_called()


if __name__ == '__main__':
    unittest.main()
