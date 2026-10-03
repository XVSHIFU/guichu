"""HTTP journal integration; simulated recycle moves only an owned temp fixture."""
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
import recycle_action


class CleanupHttpTests(unittest.TestCase):
    def test_confirmed_action_remains_visible_after_object_disappears(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'owned-fixture';target.mkdir();(target/'sample').write_text('fixture')
            preview={'path':str(target),'fingerprint':'fixture-hash','files':1,'directories':1,'bytes':7,'processes':[],'usage_check':'complete','restore_note':'Simulated recycle in test only'}
            def simulated_apply(*args,**kwargs):
                target.rename(root/'simulated-bin')
                return {'state':'recycled','path':str(target),'restore_note':'Simulated recycle in test only'}
            with patch.object(server,'DB',root/'test.db'),patch.object(server,'scan',return_value=True),patch.object(recycle_action,'preview',return_value=preview),patch.object(recycle_action,'apply',side_effect=simulated_apply):
                server.initialize()
                with server.connection() as db:db.execute('INSERT INTO scans(at,payload) VALUES (?,?)',('test',json.dumps({'objects':[{'id':'owned','kind':'directory','name':'Fixture','path':str(target)}],'relations':[]})))
                http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
                thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start();origin=f'http://127.0.0.1:{http.server_port}'
                def post(action,body):
                    request=Request(origin+'/api/cleanup/'+action,data=json.dumps(body).encode(),headers={'Origin':origin,'X-Desk-Token':server.TOKEN,'Content-Type':'application/json'})
                    with urlopen(request,timeout=3) as response:return json.load(response)
                try:
                    proposal=post('propose',{'object_id':'owned','kind':'recycle','request_id':'fixture-http'})['action']
                    self.assertTrue(target.exists())
                    action=post('confirm',{'id':proposal['id'],'revision':1,'acknowledge':True})['action']
                    self.assertEqual(action['state'],'recycled')
                    self.assertFalse(target.exists())
                    with server.connection() as db:db.execute('INSERT INTO scans(at,payload) VALUES (?,?)',('after',json.dumps({'objects':[],'relations':[]})))
                    history=post('list',{})['actions']
                    self.assertEqual(history[0]['object']['name'],'Fixture')
                    self.assertEqual(history[0]['state'],'recycled')
                finally:http.shutdown();http.server_close();thread.join(3)
