import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.previous=server.DB
        server.DB=Path(self.temp.name)/'test.sqlite3'
        server.initialize()
    def tearDown(self):
        server.DB=self.previous
        self.temp.cleanup()
    def scan(self,objects,issues=None):
        payload={'at':server.now(),'objects':objects,'relations':[],'issues':issues or []}
        with patch.object(server,'collect',return_value=payload):
            self.assertTrue(server.scan())
            for _ in range(100):
                if not server.scan_status()['running']:break
                time.sleep(.01)
            self.assertFalse(server.scan_status()['running'])
            self.assertIsNone(server.scan_status()['error'])
    def test_notes_survive_rescan_and_changes(self):
        obj={'id':'one','name':'Tool','kind':'agent','version':'1'}
        self.scan([obj])
        with server.connection() as c:c.execute('INSERT INTO notes VALUES (?,?,?,?)',('one','保留','仍在使用',server.now()))
        self.scan([{**obj,'version':'2'}])
        state=server.latest()
        self.assertEqual(state['notes']['one']['body'],'仍在使用')
        self.assertEqual(state['changes'][0]['event'],'配置变化')
        self.scan([])
        self.assertEqual(server.latest()['changes'][0]['event'],'已移除')
    def test_partial_failure_does_not_claim_removed(self):
        self.scan([{'id':'one','name':'Tool','kind':'agent'}])
        self.scan([],['读取失败'])
        self.assertEqual(server.latest()['changes'],[])
    def test_identity_case_insensitive(self):
        self.assertEqual(server.identity('skill','C:/Users/Test'),server.identity('skill','c:/users/test'))

if __name__=='__main__':unittest.main()
