"""Real HTTP and filesystem boundary exercised only in a temporary home."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.request import Request,urlopen
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server


class McpActionHttpTests(unittest.TestCase):
    def test_confirm_restore_isolated_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config=root/'.codex'/'config.toml'
            config.parent.mkdir();original=b'[mcp_servers.fixture]\ncommand = "example"\n'
            config.write_bytes(original)
            with patch.object(server,'DB',root/'db.sqlite3'),patch.object(server,'HOME',root),patch.object(server,'ROOT',root),patch.object(server,'scan',return_value=True):
                server.initialize()
                with server.connection() as db:
                    data={'objects':[{'id':'fixture-mcp','name':'fixture','kind':'mcp','scope':'codex','source':'用户配置','path':str(config)}]}
                    db.execute('INSERT INTO scans(at,payload) VALUES (?,?)',('test',json.dumps(data)))
                http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
                thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
                origin=f'http://127.0.0.1:{http.server_port}'
                def post(action,body):
                    request=Request(origin+'/api/mcp-action/'+action,data=json.dumps(body).encode(),headers={'Origin':origin,'X-Desk-Token':server.TOKEN,'Content-Type':'application/json'})
                    with urlopen(request,timeout=10) as response:return json.load(response)
                try:
                    proposal=post('propose',{'object_id':'fixture-mcp','enabled':False,'request_id':'http-fixture'})['action']
                    self.assertEqual(config.read_bytes(),original)
                    request={'id':proposal['id'],'revision':proposal['revision']}
                    applied=post('confirm',request)['action']
                    self.assertEqual(applied['state'],'applied')
                    self.assertIn(b'enabled = false',config.read_bytes())
                    self.assertEqual(post('confirm',request)['action']['state'],'applied')
                    self.assertEqual(post('restore',request)['action']['state'],'restored')
                    self.assertEqual(config.read_bytes(),original)
                    self.assertEqual(post('list',{})['actions'][0]['state'],'restored')
                finally:http.shutdown();http.server_close();thread.join(3)
