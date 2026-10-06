import base64
import io
import json
from pathlib import Path
import re
import socket
import sys
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import elevated_size as elevated
import directory_sizes as sizes

class ElevatedTests(unittest.TestCase):
    def test_protocol_rejects_truncated_messages(self):
        with self.assertRaises(ValueError): elevated._read(io.BytesIO(b'{"a":1}'))
        with self.assertRaises(ValueError): elevated._read(io.BytesIO(b''))
        self.assertEqual(elevated._read(io.BytesIO(b'{"a":1}\n')),{'a':1})

    def test_results_return_to_unelevated_persistence(self):
        saved=[]; workers=[]; failures=[]
        task={'id':'test','path':'C:\\fixture','status':'queued'}
        def spawn(args,**kwargs):
            command=args[-1]
            encoded=max(re.findall(r'[A-Za-z0-9+/=]{40,}',command),key=len)
            config=json.loads(base64.b64decode(encoded))
            self.assertIn('-Verb RunAs',command)
            def worker():
                try:
                    with socket.create_connection(('127.0.0.1',config['port'])) as client, client.makefile('rwb') as stream:
                        elevated._send(stream,{'token':config['token']})
                        elevated._read(stream)
                        elevated._send(stream,{**task,'status':'succeeded','bytes':42})
                        elevated._read(stream)
                except Exception as e: failures.append(e)
            thread=threading.Thread(target=worker); workers.append(thread);thread.start()
            return type('Process',(),{'poll':lambda self:None})()
        with patch.object(elevated.subprocess,'Popen',side_effect=spawn),patch.object(sizes,'_persist',side_effect=lambda c,t:saved.append(dict(t))):
            elevated.launch(None,task,threading.Event())
        for worker in workers:worker.join(2)
        self.assertFalse(failures)
        self.assertEqual(saved[-1]['status'],'succeeded')
        self.assertEqual(saved[-1]['bytes'],42)

    def test_declined_uac_becomes_failed_task(self):
        process=type('Process',(),{'poll':lambda self:1})()
        task={'id':'declined','path':'C:\\fixture','status':'queued'}
        with patch.object(elevated.subprocess,'Popen',return_value=process),patch.object(sizes,'_persist'):
            elevated.launch(None,task,threading.Event())
        self.assertEqual(task['status'],'failed')
        self.assertIn('授权',task['error'])
