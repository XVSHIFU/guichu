"""Catalog HTTP integration with temporary provider storage, no external requests."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from model_provider import ModelProvider

class CatalogHttpTests(unittest.TestCase):
    def test_catalog_activation_and_running_guard(self):
        with tempfile.TemporaryDirectory() as root, patch.object(server,'PROVIDER',ModelProvider(root)):
            http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
            thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
            origin=f'http://127.0.0.1:{http.server_port}'
            def post(body):
                request=Request(origin+'/api/model/catalog',data=json.dumps(body).encode(),headers={
                    'Origin':origin,'X-Desk-Token':server.TOKEN,'Content-Type':'application/json'})
                with urlopen(request,timeout=3) as response:return json.load(response)
            try:
                catalog=post({'action':'save','name':'Local test','config':{'endpoint':'http://127.0.0.1:12345/v1','model':'test'},'models':[{'id':'test','name':'Test'}]})
                provider=catalog['providers'][0]
                self.assertFalse(provider['key_configured'])
                self.assertNotIn('encrypted_key',provider)
                self.assertEqual(post({'action':'activate','id':provider['id']})['active_id'],provider['id'])
                with patch.dict(server.assistant_runtime.ACTIVE,{'test-run':threading.Event()}):
                    self.assertEqual(len(post({'action':'list'})['providers']),1)
                    with self.assertRaises(HTTPError) as error:post({'action':'delete','id':provider['id']})
                    self.assertEqual(error.exception.code,409)
                self.assertEqual(server.PROVIDER.get_public()['config']['model'],'test')
            finally:
                http.shutdown();http.server_close();thread.join(3)
