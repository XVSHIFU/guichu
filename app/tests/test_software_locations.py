import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from software_locations import automatic_sources, enrich_locations


class LocationTests(unittest.TestCase):
    def test_observed_install_and_candidate_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / 'installed'; install.mkdir()
            config = root / 'data' / 'SampleTool'; config.mkdir(parents=True)
            obj = {'id':'a', 'kind':'software', 'name':'SampleTool 8', 'path':str(install)}
            with patch.dict(os.environ, {'APPDATA':str(config.parent), 'LOCALAPPDATA':str(root/'missing'), 'PROGRAMDATA':str(root/'missing')}), patch('software_locations.Path.home', return_value=root):
                enrich_locations({'objects':[obj], 'relations':[]})
            self.assertEqual(next(x for x in obj['locations'] if x['role']=='install')['confidence'], 'observed')
            self.assertEqual(next(x for x in obj['locations'] if x['role']=='config')['confidence'], 'candidate')

    def test_duplicate_registry_views_preserve_distinct_installations(self):
        base = {'kind':'software','name':'Sample','registryHive':'HKLM','registryKey':'Sample','version':'1'}
        objects = [dict(base,id='a',path='C:/One',registryView=32),dict(base,id='b',path='C:/One',registryView=64),dict(base,id='c',path='D:/Two',registryView=64)]
        with patch('software_locations.os.scandir', side_effect=FileNotFoundError):
            result=enrich_locations({'objects':objects,'relations':[]})
        self.assertEqual(objects[1]['duplicateOf'], 'a')
        self.assertNotIn('duplicateOf',objects[2])
        self.assertEqual(len(result['objects']),3)

    def test_automatic_roots_follow_scanned_drives(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'ProgramAll').mkdir()
            with patch.dict(os.environ, {'ProgramFiles':'','ProgramFiles(x86)':'','LOCALAPPDATA':''}):
                sources=list(automatic_sources([{'path':str(root)}]))
            self.assertEqual([s['path'] for s in sources],[str(root/'ProgramAll')])
            self.assertTrue(sources[0]['id'].startswith('auto-'))

    def test_same_install_across_keys_and_program_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'SampleTool.exe').write_bytes(b'not executed')
            base={'kind':'software','name':'SampleTool 8','vendor':'Sample vendor','version':'8','path':str(root),'registryHive':'HKLM'}
            first=dict(base,id='a',registryKey='InstallShield_GUID')
            second=dict(base,id='b',registryKey='GUID')
            agent={'id':'c','kind':'agent','name':'SampleTool','path':str(root/'missing')}
            with patch.dict(os.environ, {'APPDATA':tmp,'LOCALAPPDATA':tmp,'PROGRAMDATA':tmp}),patch('software_locations.Path.home',return_value=root):
                enrich_locations({'objects':[first,second,agent],'relations':[]})
            self.assertEqual(second['duplicateOf'],'a')
            self.assertEqual(first['executable'],str(root/'SampleTool.exe'))
            self.assertEqual(agent['executable'],first['executable'])
            self.assertTrue(agent['commandFound'])


if __name__ == '__main__':
    unittest.main()
