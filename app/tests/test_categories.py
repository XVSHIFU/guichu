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


class CategoryTests(unittest.TestCase):
    def test_manual_category_survives_new_snapshot_and_can_be_cleared(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(server,'DB',Path(directory)/'test.db'):
            server.initialize()
            snapshot={'objects':[{'id':'app','kind':'software','name':'Fixture'}]}
            with server.connection() as db:db.execute('INSERT INTO scans(at,payload) VALUES (?,?)',('old',json.dumps(snapshot)))
            http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
            thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
            origin=f'http://127.0.0.1:{http.server_port}'
            def save(value):
                request=Request(origin+'/api/category',data=json.dumps({'id':'app','value':value}).encode(),headers={'Origin':origin,'X-Desk-Token':server.TOKEN,'Content-Type':'application/json'})
                with urlopen(request,timeout=3) as response:return json.load(response)
            try:
                self.assertTrue(save('办公与协作')['ok'])
                with server.connection() as db:db.execute('INSERT INTO scans(at,payload) VALUES (?,?)',('new',json.dumps(snapshot)))
                self.assertEqual(server.latest()['objects'][0]['manualCategory'],'办公与协作')
                self.assertTrue(save(None)['ok'])
                self.assertNotIn('manualCategory',server.latest()['objects'][0])
                with server.connection() as db:
                    self.assertNotIn('manualCategory',json.loads(db.execute('SELECT payload FROM scans ORDER BY id DESC LIMIT 1').fetchone()[0])['objects'][0])
            finally:http.shutdown();http.server_close();thread.join(3)
