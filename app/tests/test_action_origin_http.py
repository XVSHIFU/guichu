"""Real HTTP origin links with isolated notes and conversations only."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class OriginHttpTests(unittest.TestCase):
    def test_conversation_action_and_deleted_source_snapshot(self):
        with tempfile.TemporaryDirectory() as root, patch.object(server, 'DB', Path(root)/'test.sqlite3'):
            server.initialize()
            with server.connection() as db:
                db.execute('INSERT INTO scans(at,payload) VALUES (?,?)', ('test', json.dumps({'objects':[
                    {'id':'fixture','name':'Fixture','kind':'agent'}]})))
            http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
            thread = threading.Thread(target=http.serve_forever, daemon=True)
            thread.start()
            origin = f'http://127.0.0.1:{http.server_port}'
            def post(route, body):
                request = Request(origin+'/api/'+route, data=json.dumps(body).encode(), headers={
                    'Origin':origin, 'X-Desk-Token':server.TOKEN, 'Content-Type':'application/json'})
                with urlopen(request, timeout=3) as response:
                    return json.load(response)
            try:
                session = post('assistant/create', {'target_id':'fixture'})['session']
                self.assertEqual(session['mode'], 'readonly')
                for legacy in ('send', 'confirm'):
                    with self.assertRaises(HTTPError) as retired:
                        post('assistant/'+legacy, {'id':session['id']})
                    self.assertEqual(retired.exception.code, 410)
                self.assertEqual(post('assistant/get', {'id':session['id']})['session']['messages'], [])
                proposal = post('action/propose', {'object_id':'fixture','decision':'保留',
                    'request_id':'origin-http','origin':{'session_id':session['id']}})['action']
                self.assertEqual(server.latest()['notes'], {})
                self.assertEqual(proposal['origin']['session_id'], session['id'])
                post('action/confirm', {'id':proposal['id'],'revision':proposal['revision']})
                history = post('assistant/actions', {'id':session['id']})['actions']
                self.assertEqual(history[0]['state'], 'applied')
                self.assertEqual(history[0]['family'], 'action')
                post('assistant/delete', {'id':session['id']})
                remaining = post('action/list', {})['actions'][0]
                self.assertEqual(remaining['origin'], proposal['origin'])
                self.assertEqual(remaining['state'], 'applied')
            finally:
                http.shutdown()
                http.server_close()
                thread.join(3)
