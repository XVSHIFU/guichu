import json, sqlite3, subprocess, sys, tempfile, time, socket, threading, unittest
from pathlib import Path
from contextlib import contextmanager
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import mcp_client as client
import mcp_client_store as store

class RemoteMCPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(); cls.root=Path(cls.temp.name)
        sock=socket.socket();sock.bind(('127.0.0.1',0));cls.port=sock.getsockname()[1];sock.close()
        script=cls.root/'remote.py'
        script.write_text("""import sys,asyncio
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
app=MCPServer('http-fixture')
@app.tool(annotations=ToolAnnotations(read_only_hint=True))
def read_value(key:str)->dict:
 return {'value':key,'token':'secret-result'}
@app.tool(annotations=ToolAnnotations(read_only_hint=True))
async def slow()->str:
 await asyncio.sleep(60)
 return 'done'
app.run(transport='streamable-http',port=int(sys.argv[1]))
""",encoding='utf-8')
        cls.proc=subprocess.Popen([sys.executable,str(script),str(cls.port)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                with socket.create_connection(('127.0.0.1',cls.port),timeout=.1):break
            except OSError:time.sleep(.1)
        else:raise RuntimeError('fixture did not start')
    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate();cls.proc.wait(timeout=10);cls.temp.cleanup()
    def setUp(self):
        self.dbtemp=tempfile.TemporaryDirectory()
        @contextmanager
        def connection():
            db=sqlite3.connect(Path(self.dbtemp.name)/'db')
            try:
                with db:yield db
            finally:db.close()
        self.connection=connection;store.initialize(connection)
        self.body={'name':'Remote fixture','transport':'streamable-http','url':f'http://127.0.0.1:{self.port}/mcp','acknowledge_execution':True}
    def tearDown(self):self.dbtemp.cleanup()
    def test_transport_discovery_call_cancel_and_revoke(self):
        record=store.save(self.connection,self.body)
        result,status=store.dispatch(self.connection,'/api/mcp-client/discover',{'id':record['id'],'acknowledge_execution':True})
        self.assertEqual(status,200,result)
        store.save(self.connection,{**self.body,'id':record['id'],'enabled':True,'allowed_tools':['read_value','slow']})
        registry=client.Registry(self.connection,[record['id']])
        key=next(n for n,(_,t) in registry.tools.items() if t['name']=='read_value')
        result=registry.execute_tool(key,{'key':'hello'})
        self.assertTrue(result['ok'],result);self.assertNotIn('secret-result',json.dumps(result));self.assertIn('hello',json.dumps(result))
        slow=next(n for n,(_,t) in registry.tools.items() if t['name']=='slow')
        cancel=threading.Event();timer=threading.Timer(.4,cancel.set);timer.start()
        result=registry.execute_tool(slow,{},cancel=cancel);timer.join()
        self.assertEqual(result['error']['code'],'cancelled')
        result=registry.execute_tool(slow,{},deadline=time.monotonic()+.3)
        self.assertEqual(result['error']['code'],'timeout')
        store.save(self.connection,{**self.body,'id':record['id']})
        self.assertEqual(registry.execute_tool(key,{'key':'no'})['error']['code'],'registration_changed')
    def test_credentials_encrypted_hidden_and_destination_reset(self):
        record=store.save(self.connection,{**self.body,'token':'fixture-credential'})
        self.assertNotIn('fixture-credential',json.dumps(record))
        self.assertEqual(store.authorization(record),{'Authorization':'Bearer fixture-credential'})
        payload,status=store.dispatch(self.connection,'/api/mcp-client/list',{})
        self.assertTrue(payload['servers'][0]['has_token']);self.assertNotIn('credential',payload['servers'][0])
        changed=store.save(self.connection,{**self.body,'id':record['id'],'url':self.body['url']+'/other'})
        self.assertFalse(changed['credential'])
    def test_url_validation_and_no_redirects(self):
        for url in ['http://example.com/mcp','https://user:pass@example.com/mcp','https://example.com/mcp?token=x','file:///tmp','https://example.com/mcp#x']:
            with self.assertRaises(ValueError):store.remote_url(url)
        self.assertEqual(store.remote_url('https://example.com/mcp'),'https://example.com/mcp')
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        seen=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append(self.path);self.send_response(307);self.send_header('Location','/other');self.end_headers()
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            result=client.discover({'id':'x','transport':'streamable-http','url':f'http://127.0.0.1:{server.server_port}/mcp'},timeout=2)
            self.assertFalse(result['ok']);self.assertEqual(seen,['/mcp'])
        finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':unittest.main()
