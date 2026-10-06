import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
import source_registry


class RegisteredIntegrationTests(unittest.TestCase):
    def test_registered_project_scan_retains_failure_then_removes_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'project';project.mkdir()
            config=project/'.mcp.json'
            config.write_text(json.dumps({'mcpServers':{'fixture':{'command':'node','env':{'TOKEN':'secret-fixture-value'}}}}),encoding='utf-8')
            with patch.object(server,'DB',root/'test.db'),patch.object(server,'enrich_icons'),patch.object(server,'automatic_sources',return_value=[]),patch.object(server,'collect_packages',return_value={}),patch.object(server,'collect_windows_apps',return_value={}),patch.object(server,'collect_managers',return_value={}),patch.object(server,'collect',side_effect=lambda:{'objects':[],'relations':[],'sources':[],'issues':[],'at':server.now()}):
                server.initialize()
                result,status=source_registry.dispatch(server.connection,'/api/source/add',{'type':'project','path':str(project),'label':'Fixture'})
                self.assertEqual(status,200)
                server.scan_collect()
                first=server.latest();mcp=next(o for o in first['objects'] if o['kind']=='mcp')
                self.assertNotIn('secret-fixture-value',json.dumps(first))
                config.write_text('{broken',encoding='utf-8')
                server.scan_collect()
                retained=next(o for o in server.latest()['objects'] if o['id']==mcp['id'])
                self.assertTrue(retained['stale'])
                self.assertEqual(retained['checkedAt'],mcp['checkedAt'])
                source_registry.dispatch(server.connection,'/api/source/remove',{'id':result['source']['id']})
                server.scan_collect()
                self.assertEqual(server.latest()['objects'],[])
                self.assertTrue(project.is_dir())
                self.assertEqual(config.read_text(encoding='utf-8'),'{broken')
