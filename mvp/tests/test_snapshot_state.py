import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from snapshot_state import reconcile
class SnapshotTests(unittest.TestCase):
    def test_failed_source_preserved_successful_removal_visible(self):
        old={'objects':[{'id':'a','kind':'skill','sourceKey':'agent-config'},{'id':'b','kind':'software','sourceKey':'software-registry'}]}
        new={'objects':[],'sources':[{'id':'agent-config','status':'partial'},{'id':'software-registry','status':'success'}]}
        result=reconcile(old,new)
        self.assertEqual([o['id'] for o in result['objects']],['a'])
        self.assertTrue(result['objects'][0]['stale'])
