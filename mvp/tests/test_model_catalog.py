import base64
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model_provider import DEFAULTS, ModelProvider, ProviderError


class ModelCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.provider = ModelProvider(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def save(self, name='Fixture', endpoint='http://127.0.0.1:12345/v1', model='model-a', **extra):
        return self.provider.catalog(dict(action='save', name=name,
            config=dict(endpoint=endpoint, model=model), models=[{'id': model, 'name': model}] if model else [], **extra))

    @contextmanager
    def remote(self):
        state = dict(status=200, payload={'data': [{'id': 'remote-a', 'name': '远端模型', 'extra': 'ignored'}]}, requests=[], silent=False)
        release = threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                state['requests'].append({'method': 'GET', 'path': self.path, 'authorization': self.headers.get('Authorization')})
                self.send_response(state['status'])
                self.send_header('Content-Type', 'application/json')
                if state['status'] == 302:
                    self.send_header('Location', '/must-not-follow')
                self.end_headers()
                self.wfile.flush()
                if state['silent']:
                    release.wait(3)
                    return
                raw = state.get('raw', json.dumps(state['payload']).encode())
                self.wfile.write(raw)
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                state['requests'].append({'method': 'POST', 'path': self.path, 'authorization': self.headers.get('Authorization'), 'body': body})
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                self.wfile.write(b'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}/api/v1', state
        finally:
            release.set()
            server.shutdown()
            server.server_close()

    def test_v1_list_does_not_write_or_decrypt_and_save_preserves_ciphertext(self):
        cipher = base64.b64encode(b'synthetic-existing-dpapi-blob').decode()
        original = json.dumps(dict(version=1, config=dict(DEFAULTS, endpoint='https://example.com/v1', model='legacy-model'), encrypted_key=cipher)).encode()
        self.provider.path.write_bytes(original)
        with patch('model_provider._crypt', side_effect=AssertionError('must not decrypt')):
            public = self.provider.catalog({'action': 'list'})
            self.assertEqual(public['active_id'], 'legacy')
            self.assertEqual(public['providers'][0]['models'], [{'id': 'legacy-model', 'name': 'legacy-model'}])
            self.assertEqual(self.provider.get_public()['provider_id'], 'legacy')
            self.assertEqual(self.provider.path.read_bytes(), original)
            self.provider.catalog({'action': 'save', 'id': 'legacy', 'name': '重命名'})
        stored = json.loads(self.provider.path.read_text(encoding='utf-8'))
        self.assertEqual(stored['version'], 2)
        self.assertEqual(stored['providers'][0]['encrypted_key'], cipher)
        self.assertNotIn(cipher, json.dumps(public))

    def test_multiple_providers_activation_strict_models_and_legacy_configure(self):
        first = self.save()['active_id']
        result = self.save(name='Second', endpoint='https://example.com/v1', model='model-b')
        second = result['providers'][1]['id']
        self.assertEqual(result['active_id'], first)
        with self.assertRaises(ProviderError):
            self.provider.catalog({'action': 'delete', 'id': first})
        with self.assertRaises(ProviderError):
            self.provider.catalog({'action': 'save', 'id': first, 'models': [{'id': 'replacement'}]})
        self.provider.catalog({'action': 'save', 'id': first, 'models': [{'id': 'replacement'}, {'id': 'replacement'}], 'config': {'model': 'replacement'}})
        self.provider.configure({'model': 'legacy-manual-model'})
        self.assertEqual(len(self.provider.catalog({'action': 'list'})['providers'][0]['models']), 2)
        self.provider.catalog({'action': 'activate', 'id': second, 'model': 'model-b'})
        self.assertEqual(self.provider.get_public()['provider_id'], second)
        self.assertEqual(self.provider.get_public()['config']['model'], 'model-b')
        self.provider.catalog({'action': 'delete', 'id': first})
        with self.assertRaises(ProviderError):
            self.provider.catalog({'action': 'delete', 'id': second})

    def test_new_connection_can_be_saved_before_model_selection(self):
        result = self.save(model='')
        self.assertIsNone(result['active_id'])
        provider_id = result['providers'][0]['id']
        self.assertEqual(self.provider.get_public()['config']['model'], '')
        with self.assertRaises(ProviderError):
            self.provider.catalog({'action': 'activate', 'id': provider_id})
        result = self.provider.catalog({'action': 'save', 'id': provider_id, 'models': [{'id': 'chosen'}], 'config': {'model': 'chosen'}})
        self.assertEqual(result['active_id'], provider_id)

    @unittest.skipUnless(os.name == 'nt', 'DPAPI on Windows')
    def test_keys_are_per_provider_and_endpoint_change_clears_only_edited_key(self):
        first = self.save(api_key='synthetic-first-key')['active_id']
        result = self.save(name='Second', api_key='synthetic-second-key')
        second = result['providers'][1]['id']
        self.assertTrue(all(item['key_configured'] for item in result['providers']))
        result = self.provider.catalog({'action': 'save', 'id': first, 'config': {'endpoint': 'https://different.example/v1'}})
        self.assertFalse(result['providers'][0]['key_configured'])
        self.assertTrue(result['providers'][1]['key_configured'])
        self.assertNotIn('synthetic', self.provider.path.read_text(encoding='utf-8'))
        self.assertNotIn('encrypted_key', json.dumps(result))
        result = self.provider.catalog({'action': 'save', 'id': second, 'clear_key': True})
        self.assertFalse(result['providers'][1]['key_configured'])

    def test_fetch_models_is_manual_same_origin_bounded_deduplicated_and_not_saved(self):
        with self.remote() as (endpoint, remote):
            catalog = self.save(endpoint=endpoint, model='')
            provider_id = catalog['providers'][0]['id']
            before = self.provider.path.read_bytes()
            self.assertEqual(remote['requests'], [])
            remote['payload'] = {'data': [{'id': 'duplicate'}, {'id': 'duplicate'}, {'id': 'bad\nmodel'}, {'id': ['bad']}, *[{'id': 'model-'+str(i), 'name': 'Name '+str(i), 'extra': 'ignored'} for i in range(600)]]}
            result = self.provider.catalog({'action': 'models', 'id': provider_id})
            self.assertEqual(len(result['models']), 500)
            self.assertEqual(len({item['id'] for item in result['models']}), 500)
            self.assertTrue(all(set(item) == {'id', 'name'} for item in result['models']))
            self.assertEqual(remote['requests'][0]['path'], '/api/v1/models')
            self.assertEqual(self.provider.path.read_bytes(), before)
            self.assertEqual(self.provider.catalog({'action': 'list'}), catalog)

    def test_model_fetch_redirect_errors_and_limits_are_safe(self):
        with self.remote() as (endpoint, remote):
            provider_id = self.save(endpoint=endpoint)['active_id']
            for status, code in [(302, 'redirect'), (404, 'unsupported'), (401, 'http_error')]:
                remote['status'] = status
                remote['payload'] = {'error': 'synthetic-sensitive-diagnostic'}
                with self.assertRaises(ProviderError) as caught:
                    self.provider.catalog({'action': 'models', 'id': provider_id})
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn('sensitive', str(caught.exception))
            self.assertEqual(len(remote['requests']), 3)
            self.assertTrue(all(item['path'] == '/api/v1/models' for item in remote['requests']))
            remote['status'] = 200
            remote['raw'] = b'x' * (2 * 1024 * 1024 + 1)
            with self.assertRaises(ProviderError) as caught:
                self.provider.catalog({'action': 'models', 'id': provider_id})
            self.assertEqual(caught.exception.code, 'limit')

    def test_models_deadline_interrupts_silent_http(self):
        with self.remote() as (endpoint, remote):
            provider_id = self.save(endpoint=endpoint)['active_id']
            self.provider.catalog({'action': 'save', 'id': provider_id, 'config': {'timeout': 1}})
            remote['silent'] = True
            started = time.monotonic()
            with self.assertRaises(ProviderError) as caught:
                self.provider.catalog({'action': 'models', 'id': provider_id})
            self.assertEqual(caught.exception.code, 'timeout')
            self.assertLess(time.monotonic() - started, 2.5)

    def test_named_test_does_not_change_active_or_send_user_context(self):
        first = self.save()['active_id']
        with self.remote() as (endpoint, remote):
            result = self.save(name='Test target', endpoint=endpoint, model='test-other-model')
            second = result['providers'][1]['id']
            before = self.provider.path.read_bytes()
            tested = self.provider.catalog({'action': 'test', 'id': second})
            self.assertTrue(tested['ok'])
            self.assertEqual(tested['provider_id'], second)
            self.assertEqual(tested['model'], 'test-other-model')
            self.assertEqual(self.provider.catalog({'action': 'list'})['active_id'], first)
            self.assertEqual(self.provider.path.read_bytes(), before)
            self.assertEqual(remote['requests'][0]['body']['messages'], [{'role': 'user', 'content': 'Reply with OK.'}])

    def test_validation_rejects_unknown_ids_and_malformed_lists_without_network(self):
        first = self.save()['active_id']
        with patch('model_provider.http.client.HTTPConnection', side_effect=AssertionError('unexpected network')):
            for body in ({'action': []}, {'action': 'activate', 'id': first, 'model': 'not-saved'},
                         {'action': 'models', 'id': 'missing'}, {'action': 'save', 'id': first, 'models': [{'id': 'x'*201}]},
                         {'action': 'save', 'id': first, 'models': [{'id': str(i)} for i in range(501)]}):
                with self.subTest(body=str(body)[:100]), self.assertRaises(ProviderError):
                    self.provider.catalog(body)


if __name__ == '__main__':
    unittest.main()
