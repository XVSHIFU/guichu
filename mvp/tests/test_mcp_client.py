import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mcp_client
import mcp_client_store as store


FIXTURE = '''
import asyncio, os, pathlib, sys
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))
app=MCPServer('local-test')
@app.tool(description='Read a fixed fixture value', annotations=ToolAnnotations(read_only_hint=True))
def read_value(key: str) -> dict:
    return {'value':key, 'api_key':'fixture-secret'}
@app.tool(annotations=ToolAnnotations(read_only_hint=True))
async def slow() -> str:
    await asyncio.sleep(60)
    return 'done'
@app.tool(annotations=ToolAnnotations(read_only_hint=True))
def long_text() -> str:
    return 'x'*100000
@app.tool(annotations=ToolAnnotations(read_only_hint=True))
def disconnect() -> str:
    os._exit(9)
@app.tool()
def not_approved() -> str:
    return 'not allowed'
app.run(transport='stdio')
'''


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.script = self.root / 'fixture.py'
        self.pidfile = self.root / 'pid'
        self.script.write_text(FIXTURE, encoding='utf-8')
        @contextmanager
        def connection():
            db = sqlite3.connect(self.root / 'test.sqlite', timeout=5)
            try:
                with db:
                    yield db
            finally:
                db.close()
        self.connection = connection
        store.initialize(self.connection)
        self.record = store.save(self.connection, {'name': 'Temporary MCP fixture', 'command': sys.executable,
                    'args': [str(self.script), str(self.pidfile)], 'cwd': str(self.root),
                    'enabled': False, 'allowed_tools': [], 'acknowledge_execution': True})

    def tearDown(self):
        self.assert_dead()
        self.temp.cleanup()

    def assert_dead(self):
        if self.pidfile.exists():
            pid = int(self.pidfile.read_text())
            self.assertFalse(psutil.pid_exists(pid), f'fixture process {pid} leaked')

    def enable(self, names):
        result, status = store.dispatch(self.connection, '/api/mcp-client/discover', {'id': self.record['id'], 'acknowledge_execution': True})
        self.assertEqual(status, 200, result)
        self.assert_dead()
        self.record = result['server']
        body = {k: self.record[k] for k in ('id', 'name', 'command', 'args', 'cwd')}
        self.record = store.save(self.connection, {**body, 'enabled': True, 'allowed_tools': names, 'acknowledge_execution': True})
        return mcp_client.Registry(self.connection, [self.record['id']])

    def tool(self, registry, original):
        return next(name for name, (_, t) in registry.tools.items() if t['name'] == original)

    def test_explicit_discovery_call_redaction_and_scope(self):
        self.assertEqual(mcp_client.Registry(self.connection, [self.record['id']]).tools_catalog(), [])
        self.assertFalse(self.pidfile.exists())
        registry = self.enable(['read_value'])
        self.assertEqual(len(registry.tools_catalog()), 1)
        result = registry.execute_tool(self.tool(registry, 'read_value'), {'key': 'fixture'})
        self.assertTrue(result['ok'], result)
        self.assertNotIn('fixture-secret', json.dumps(result))
        self.assertIn('fixture', json.dumps(result['data']))
        self.assertEqual(registry.execute_tool('not_approved', {})['error']['code'], 'tool_not_allowed')
        self.assertEqual(mcp_client.Registry(self.connection, []).tools_catalog(), [])
        self.assert_dead()

    def test_timeout_cancellation_and_process_cleanup(self):
        registry = self.enable(['slow'])
        tool = self.tool(registry, 'slow')
        result = registry.execute_tool(tool, {}, deadline=time.monotonic() + 3)
        self.assertEqual(result['error']['code'], 'timeout', result)
        self.assert_dead()
        stop = threading.Event()
        timer = threading.Timer(3, stop.set)
        timer.start()
        try:
            result = registry.execute_tool(tool, {}, cancel=stop)
        finally:
            timer.join()
        self.assertEqual(result['error']['code'], 'cancelled', result)
        self.assert_dead()

    def test_changed_definition_disconnect_and_long_output(self):
        registry = self.enable(['read_value', 'disconnect', 'long_text'])
        result = registry.execute_tool(self.tool(registry, 'long_text'), {})
        self.assertTrue(result['ok'], result)
        self.assertTrue(result['truncated'])
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode()), 32768)
        result = registry.execute_tool(self.tool(registry, 'disconnect'), {})
        self.assertFalse(result['ok'])
        self.assert_dead()
        self.script.write_text(FIXTURE.replace('Read a fixed fixture value', 'Changed contract'), encoding='utf-8')
        result = registry.execute_tool(self.tool(registry, 'read_value'), {'key': 'a'})
        self.assertEqual(result['error']['code'], 'tool_changed', result)

    def test_bad_arguments_revoke_and_disabled_discovery(self):
        registry = self.enable(['read_value'])
        name = self.tool(registry, 'read_value')
        self.assertEqual(registry.execute_tool(name, {'key': 3})['error']['code'], 'invalid_arguments')
        result, code = store.dispatch(self.connection, '/api/mcp-client/discover', {'id': self.record['id'], 'acknowledge_execution': True})
        self.assertEqual(code, 200)
        self.assertFalse(result['server']['enabled'])
        self.assertEqual(result['server']['allowed_tools'], [])
        self.assertEqual(registry.execute_tool(name, {'key': 'a'})['error']['code'], 'registration_changed')

    def test_registration_validation_and_start_failure(self):
        with self.assertRaises(ValueError):
            store.save(self.connection, {'command': 'python fixture.py', 'acknowledge_execution': True})
        with self.assertRaises(ValueError):
            store.save(self.connection, {**{k: self.record[k] for k in ('id', 'name', 'command', 'args', 'cwd')},
                'enabled': True, 'allowed_tools': ['read_value'], 'acknowledge_execution': True})
        self.script.write_text('raise RuntimeError("private fixture error")', encoding='utf-8')
        result = mcp_client.discover(self.record)
        self.assertFalse(result['ok'])
        self.assertNotIn('private fixture error', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
