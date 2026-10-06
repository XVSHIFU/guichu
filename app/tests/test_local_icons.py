import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import local_icons

class IconTests(unittest.TestCase):
    def test_appx_scale_asset_and_escape_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'Assets').mkdir()
            (root/'Assets/Icon.scale-200.png').write_bytes(b'asset')
            (root/'AppxManifest.xml').write_text('<Package><Visual Square44x44Logo="Assets/Icon.png" Logo="../outside.png"/></Package>')
            resources=local_icons.appx_resources({'path':str(root)})
            self.assertEqual([p.name for p,_,_ in resources],['Icon.scale-200.png'])

    def test_missing_registered_icon_falls_back_and_first_scan_attaches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);exe=root/'app.exe';exe.write_bytes(b'exe')
            obj={'kind':'agent','name':'Example','_displayIcon':'missing','executable':str(exe)}
            def extract(args,**kwargs):
                import json
                manifest=Path(args[args.index('-Manifest')+1])
                for item in json.loads(manifest.read_text()):
                    (root/'cache'/ (item['key']+'.png')).write_bytes(b'png')
                return type('Result',(),{'returncode':0})()
            with patch.object(local_icons,'CACHE',root/'cache'),patch.object(local_icons,'shortcut_resources',return_value={}),patch.object(local_icons.subprocess,'run',side_effect=extract) as run:
                local_icons.enrich_icons([obj])
                self.assertIn('/local-icons/',obj['iconUrl'])
                self.assertEqual(obj['iconSource'],'程序图标')
                local_icons.enrich_icons([obj])
                self.assertEqual(run.call_count,1)

    def test_invalid_manifest_does_not_break_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'AppxManifest.xml').write_text('<bad')
            self.assertEqual(local_icons.appx_resources({'path':str(root)}),[])
