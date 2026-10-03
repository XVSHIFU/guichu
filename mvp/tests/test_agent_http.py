"""Full HTTP proposal flow against a temporary home, never user configuration."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from urllib.request import Request,urlopen
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

class Provider:
    def get_public(self):return {'config':{'model':'fixture','timeout':10}}
    def stream_completion(self,messages,catalog,cancel,deadline):
        yield {'type':'tool_call','id':'change-1','name':'propose_change','arguments':json.dumps({'object_id':'fixture','action':'mcp_enabled','parameters':{'decision':None,'enabled':False}})}

class AgentHttpTests(unittest.TestCase):
    def test_chat_proposal_confirm_and_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config=root/'.codex/config.toml';config.parent.mkdir();original=b'[mcp_servers.fixture]\ncommand = "fixture"\n';config.write_bytes(original)
            with patch.object(server,'DB',root/'db.sqlite3'),patch.object(server,'HOME',root),patch.object(server,'ROOT',root),patch.object(server,'PROVIDER',Provider()),patch.object(server,'scan',return_value=True):
                server.initialize()
                with server.connection() as db:
                    db.execute('INSERT INTO scans(at,payload) VALUES (?,?)',('test',json.dumps({'objects':[{'id':'fixture','name':'fixture','kind':'mcp','scope':'codex','source':'用户配置','path':str(config)}]})))
                http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start();origin=f'http://127.0.0.1:{http.server_port}'
                def post(route,body):
                    req=Request(origin+'/api/'+route,data=json.dumps(body).encode(),headers={'Origin':origin,'X-Desk-Token':server.TOKEN,'Content-Type':'application/json'})
                    with urlopen(req,timeout=10) as response:return json.load(response)
                try:
                    self.assertEqual(post('agent/preferences',{'instructions':'简洁回答'})['preferences']['instructions'],'简洁回答')
                    self.assertEqual(post('mcp-client/list',{})['servers'],[])
                    session=post('assistant/create',{})['session']
                    rid=post('run/start',{'session_id':session['id'],'text':'停用fixture','request_id':'http-test','allow_context':True})['run']['id']
                    until=time.monotonic()+10
                    while time.monotonic()<until:
                        run=post('run/get',{'id':rid})['run']
                        if run['status'] not in {'queued','running'}:break
                        time.sleep(.02)
                    self.assertEqual(run['status'],'awaiting_confirmation',post('run/get',{'id':rid}));self.assertEqual(config.read_bytes(),original)
                    proposal=run['proposals'][0];body={'session_id':session['id'],'proposal_id':proposal['id'],'revision':proposal['revision'],'request_id':'confirm-http'}
                    result=post('agent/confirm',body)
                    self.assertEqual(result['proposal']['state'],'applied');self.assertIn(b'enabled = false',config.read_bytes())
                    count=len(result['session']['messages'])
                    self.assertEqual(len(post('agent/confirm',body)['session']['messages']),count)
                    self.assertEqual(post('agent/command',{'text':'/changes','session_id':session['id']})['navigate'],'actions')
                finally:http.shutdown();http.server_close();thread.join(3)
