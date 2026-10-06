from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import file_actions

class FileActionsTests(unittest.TestCase):
    def test_open_document_and_reveal_use_literal_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'file with spaces.txt';path.write_text('test')
            with patch.object(file_actions.psutil,'disk_partitions',return_value=[SimpleNamespace(mountpoint=path.anchor)]),patch.object(file_actions.os,'startfile',create=True) as opened,patch.object(file_actions.subprocess,'Popen') as reveal:
                self.assertEqual(file_actions.dispatch({'action':'open','path':str(path)})[1],200)
                opened.assert_called_once_with(str(path.resolve()))
                self.assertEqual(file_actions.dispatch({'action':'reveal','path':str(path)})[1],200)
                self.assertEqual(reveal.call_args.args[0][-1],str(path.resolve()))

    def test_executable_and_missing_file_are_not_launched(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'test.exe';path.write_bytes(b'not executable')
            with patch.object(file_actions.psutil,'disk_partitions',return_value=[SimpleNamespace(mountpoint=path.anchor)]),patch.object(file_actions.os,'startfile',create=True) as opened:
                for target in [str(path),str(path.parent/'missing.txt'),'https://example.com','relative.txt',str(path)+':stream.txt']:
                    self.assertEqual(file_actions.dispatch({'action':'open','path':target})[1],400)
                opened.assert_not_called()

    def test_unknown_action_rejected(self):
        self.assertEqual(file_actions.dispatch({'action':'run','path':'C:/test.exe'})[1],400)

if __name__=='__main__':unittest.main()
