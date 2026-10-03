import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model_provider import ModelProvider, ProviderError


def sse(*chunks):
    return ''.join('data: ' + (c if isinstance(c, str) else json.dumps(c)) + '\n\n' for c in chunks).encode()


class Response(io.BytesIO):
    def __init__(self, data, status=200):
        super().__init__(data)
        self.status = status

    def getheader(self, name, default=''):
        return 'text/event-stream'


class Connection:
    sock = None
    def __init__(self, response):
        self.response = response
        self.requests = []
    def request(self, *args, **kwargs):
        self.requests.append((args, kwargs))
    def getresponse(self):
        return self.response
    def close(self):
        pass


class ModelProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.provider = ModelProvider(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def configure(self, **extra):
        return self.provider.configure(dict(endpoint='http://127.0.0.1:12345/v1', model='test-model', **extra))

    def stream(self, response):
        connection = Connection(response)
        with patch('model_provider.http.client.HTTPConnection', return_value=connection):
            result = list(self.provider.stream_completion([{'role': 'user', 'content': 'test'}]))
        return result, connection

    def test_configuration_never_connects_and_validates_endpoint(self):
        with patch('model_provider.http.client.HTTPConnection', side_effect=AssertionError('unexpected network')):
            self.assertFalse(self.provider.get_public()['key_configured'])
            public = self.configure(timeout=5)
            self.assertTrue(public['config']['endpoint'].endswith('/v1/chat/completions'))
            self.assertEqual(ModelProvider(self.temp.name).get_public(), public)
            nested = self.provider.configure({'config': {'model': 'nested-model'}, 'clear_key': True})
            self.assertEqual(nested['config']['model'], 'nested-model')
            self.assertFalse(nested['key_configured'])
            for endpoint in ['http://example.com/v1', 'https://user:secret@example.com/v1', 'https://example.com/?key=secret', 'file:///abc', 'https://example.com/#fragment']:
                with self.subTest(endpoint=endpoint), self.assertRaises(ProviderError):
                    self.provider.configure({'endpoint': endpoint})
            with self.assertRaises(ProviderError):
                self.provider.configure({'timeout': True})

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI')
    def test_dpapi_roundtrip_and_secret_never_public(self):
        key = 'synthetic-test-key-only'
        public = self.configure(api_key=key)
        self.assertTrue(public['key_configured'])
        self.assertNotIn(key, json.dumps(public))
        self.assertNotIn(key, self.provider.path.read_text(encoding='utf-8'))
        events, connection = self.stream(Response(sse({'choices': [{'delta': {'content': 'OK'}, 'finish_reason': 'stop'}]}, '[DONE]')))
        self.assertEqual(connection.requests[0][1]['headers']['Authorization'], 'Bearer ' + key)
        self.assertTrue(self.provider.configure({'model': 'another-model'})['key_configured'])
        self.assertFalse(self.provider.configure({'config': {}, 'clear_key': True})['key_configured'])
        self.provider.configure({'api_key': key})
        self.assertFalse(self.provider.configure({'endpoint': 'http://127.0.0.1:12346/v1'})['key_configured'])

    def test_stream_aggregates_tools_text_and_usage(self):
        self.configure()
        events, connection = self.stream(Response(sse(
            {'choices': [{'delta': {'content': '检查中', 'tool_calls': [{'index': 0, 'id': 'call_1', 'function': {'name': 'lookup', 'arguments': '{"id":'}}]}}]},
            {'choices': [{'delta': {'tool_calls': [{'index': 0, 'function': {'arguments': '"a"}'}}]}, 'finish_reason': 'tool_calls'}]},
            {'choices': [], 'usage': {'total_tokens': 12, 'untrusted': 'ignore'}}, '[DONE]')))
        self.assertEqual(events[0], {'type': 'text', 'text': '检查中'})
        self.assertEqual(events[1], {'type': 'usage', 'usage': {'total_tokens': 12}})
        self.assertEqual(events[2], {'type': 'tool_call', 'id': 'call_1', 'name': 'lookup', 'arguments': '{"id":"a"}'})
        self.assertEqual(events[3]['type'], 'done')
        self.assertNotIn('Authorization', connection.requests[0][1]['headers'])

    def test_redirect_errors_and_truncation_are_safe(self):
        self.configure()
        for response, code in [(Response(b'leaked-secret', 302), 'redirect'),
                               (Response(b'leaked-secret', 401), 'http_error'),
                               (Response(sse({'error': {'message': 'leaked-secret'}})), 'remote_error'),
                               (Response(sse({'choices': [{'delta': {'content': 'partial'}}]})), 'incomplete')]:
            with self.subTest(code=code), self.assertRaises(ProviderError) as caught:
                self.stream(response)
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn('leaked-secret', str(caught.exception))

    def test_invalid_or_incomplete_tool_never_emitted(self):
        self.configure()
        response = Response(sse({'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'c', 'function': {'name': 'lookup', 'arguments': '{'}}]}, 'finish_reason': 'tool_calls'}]}, '[DONE]'))
        with self.assertRaises(ProviderError) as caught:
            self.stream(response)
        self.assertEqual(caught.exception.code, 'protocol')

    def test_pre_cancel_and_expired_deadline_never_connect(self):
        self.configure()
        cancel = threading.Event()
        cancel.set()
        with patch('model_provider.http.client.HTTPConnection', side_effect=AssertionError('unexpected connection')):
            for kwargs, code in [({'cancel_event': cancel}, 'cancelled'), ({'deadline': time.monotonic() - 1}, 'timeout')]:
                with self.assertRaises(ProviderError) as caught:
                    list(self.provider.stream_completion([], **kwargs))
                self.assertEqual(caught.exception.code, code)

    def test_cancel_interrupts_silent_loopback_stream(self):
        self.check_silent_stream('cancelled')

    def test_deadline_interrupts_silent_loopback_stream(self):
        self.check_silent_stream('timeout')

    def check_silent_stream(self, expected):
        entered = threading.Event()
        release = threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                self.wfile.flush()
                entered.set()
                release.wait(3)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        cancel = threading.Event()
        errors = []
        def consume():
            try:
                deadline = time.monotonic() + 0.2 if expected == 'timeout' else None
                list(self.provider.stream_completion([], cancel_event=cancel, deadline=deadline))
            except ProviderError as exc:
                errors.append(exc.code)
        try:
            self.provider.configure({'endpoint': f'http://127.0.0.1:{server.server_port}/v1', 'model': 'test', 'timeout': 5})
            worker = threading.Thread(target=consume, daemon=True)
            worker.start()
            self.assertTrue(entered.wait(2))
            if expected == 'cancelled':
                cancel.set()
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [expected])
        finally:
            release.set()
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
