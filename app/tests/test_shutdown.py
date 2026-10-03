import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server


class ShutdownTests(unittest.TestCase):
    def test_busy_refusal_then_graceful_stop(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(server,'DB',Path(directory)/'test.db'),patch.object(server,'SERVICE',{'requests':0,'stopping':False}),patch.object(server,'scan_status',return_value={'running':True,'error':None}) as scan_state:
            server.initialize()
            http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
            thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
            origin=f'http://127.0.0.1:{http.server_port}'
            def stop():
                request=Request(origin+'/api/shutdown',data=b'{}',headers={'Origin':origin,'X-Desk-Token':server.TOKEN,'Content-Type':'application/json'})
                with urlopen(request,timeout=3) as response:return json.load(response)
            try:
                with self.assertRaises(HTTPError) as caught:stop()
                self.assertEqual(caught.exception.code,409)
                self.assertFalse(server.SERVICE['stopping'])
                scan_state.return_value={'running':False,'error':None}
                self.assertTrue(stop()['ok'])
                thread.join(3)
                self.assertFalse(thread.is_alive())
                self.assertTrue(server.SERVICE['stopping'])
            finally:http.shutdown();http.server_close();thread.join(3)
