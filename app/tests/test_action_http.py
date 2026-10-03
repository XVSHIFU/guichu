"""Exercise real HTTP handlers against an isolated database, never user notes."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class ActionHttpTests(unittest.TestCase):
    def test_preview_confirm_restore_through_http(self):
        with tempfile.TemporaryDirectory() as root, patch.object(server, 'DB', Path(root)/'test.sqlite3'):
            server.initialize()
            with server.connection() as db:
                db.execute('INSERT INTO scans(at,payload) VALUES (?,?)', ('test', json.dumps({'objects':[{'id':'fixture','name':'Fixture','kind':'agent'}]})))
            http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
            thread = threading.Thread(target=http.serve_forever, daemon=True)
            thread.start()
            origin = f'http://127.0.0.1:{http.server_port}'
            def post(action, body):
                request = Request(origin+'/api/action/'+action, data=json.dumps(body).encode(), headers={'Origin':origin, 'X-Desk-Token':server.TOKEN, 'Content-Type':'application/json'})
                with urlopen(request, timeout=3) as response:
                    return json.load(response)
            try:
                proposal = post('propose', {'object_id':'fixture','decision':'保留','request_id':'http-test'})['action']
                self.assertEqual(server.latest()['notes'], {})
                payload = {'id':proposal['id'], 'revision':proposal['revision']}
                self.assertEqual(post('confirm', payload)['action']['state'], 'applied')
                self.assertEqual(server.latest()['notes']['fixture']['decision'], '保留')
                self.assertEqual(post('restore', payload)['action']['state'], 'restored')
                self.assertEqual(server.latest()['notes'], {})
                self.assertEqual(post('list', {})['actions'][0]['state'], 'restored')
            finally:
                http.shutdown()
                http.server_close()
                thread.join(3)
