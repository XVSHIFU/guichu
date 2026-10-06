import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from software_origin import enrich, valid_override

class OriginTests(unittest.TestCase):
    def test_catalog_and_homepage_are_not_install_history(self):
        obj={'kind':'software','registryKey':'example','windowsInstaller':True,'homepage':'https://github.com/example/app','wingetSource':'winget'}
        enrich(obj)
        self.assertEqual(obj['softwareOrigin']['channel'],'未知')
        self.assertEqual(obj['softwareOrigin']['download'],'未知')
        self.assertEqual(obj['softwareOrigin']['method'],'MSI')

    def test_python_metadata_does_not_mean_pip(self):
        obj={'kind':'software','distribution':'pip'}
        enrich(obj)
        self.assertEqual(obj['softwareOrigin']['channel'],'未知')
        obj['packageInstaller']='uv'
        enrich(obj)
        self.assertEqual(obj['softwareOrigin']['channel'],'uv')

    def test_override_and_reset_preserve_detected_values(self):
        obj={'kind':'software','distribution':'pip','packageInstaller':'pip'}
        enrich(obj,{'channel':'Conda','download':'本地 / 离线文件'})
        self.assertEqual(obj['softwareOrigin']['manualFields'],['channel','download'])
        self.assertEqual(obj['detectedOrigin']['channel'],'pip')
        enrich(obj,{})
        self.assertEqual(obj['softwareOrigin']['channel'],'pip')
        self.assertEqual(obj['softwareOrigin']['download'],'未知')

    def test_invalid_overrides(self):
        for value in (None,[],{'channel':[]},{'evidence':'fake'},{'channel':'invented'}):
            self.assertFalse(valid_override(value))
        self.assertTrue(valid_override({}))
