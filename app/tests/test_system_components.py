import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from system_components import enrich

class ComponentTests(unittest.TestCase):
    def test_filepicker_has_friendly_name(self):
        obj={'kind':'software','name':'guid','packageFamily':'x','path':r'C:\Windows\SystemApps\Microsoft.Windows.FilePicker_cw5n1h2txyewy','packageSignature':'System'}
        enrich(obj)
        self.assertTrue(obj['systemComponent'])
        self.assertEqual(obj['name'],'Windows 文件选择器')

    def test_microsoft_publisher_or_similar_name_is_not_enough(self):
        for obj in [{'kind':'software','name':'Microsoft Edge','vendor':'Microsoft'}, {'kind':'software','name':'Microsoft.Windows.FilePicker','appxName':'Microsoft.Windows.FilePicker','path':r'D:\Apps\Fake'}]:
            enrich(obj);self.assertFalse(obj['systemComponent'])

    def test_nonremovable_metadata(self):
        obj={'kind':'software','name':'component','packageFamily':'x','nonRemovable':True}
        enrich(obj);self.assertTrue(obj['systemComponent'])
