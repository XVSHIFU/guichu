"""Explicit, bounded OpenAI-compatible streaming; credentials use Windows DPAPI.

No environment credentials, automatic requests, redirects, or request logging.
Reference: https://developers.openai.com/api/docs/guides/function-calling
"""
import base64
import copy
import ctypes
import http.client
import ipaddress
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import uuid
from urllib.parse import urlsplit, urlunsplit


class ProviderError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _crypt(data, decrypt=False):
    if os.name != 'nt':
        raise ProviderError('credential_storage', '密钥加密仅支持 Windows DPAPI')
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ProviderError('credential_storage', '无法加密或解密连接密钥，请重新填写')
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel32.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))


from agent_budget import DEFAULTS as BUDGET_DEFAULTS, LIMITS
DEFAULTS = dict(endpoint='', model='', **BUDGET_DEFAULTS)


def _endpoint(value):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 for c in value):
        raise ProviderError('validation', '端点地址格式无效')
    try:
        parts = urlsplit(value)
        port = parts.port
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError()
        if parts.scheme == 'http':
            try:
                loopback = ipaddress.ip_address(parts.hostname).is_loopback
            except ValueError:
                loopback = parts.hostname.lower() == 'localhost'
            if not loopback:
                raise ValueError()
        parts.netloc.encode('ascii')
        parts.path.encode('ascii')
    except (ValueError, UnicodeError):
        raise ProviderError('validation', '仅支持 HTTPS 或本机回环 HTTP 地址；不能包含账号、查询参数或片段') from None
    path = parts.path.rstrip('/')
    if not path.endswith('/chat/completions'):
        path += '/chat/completions'
    return urlunsplit((parts.scheme, parts.netloc, path, '', ''))


class ModelProvider:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / 'model-provider.json'
        self.lock = threading.RLock()

    def _read_catalog(self):
        if not self.path.exists():
            return dict(version=2, providers=[], active_id=None)
        try:
            if self.path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError()
            stored = json.loads(self.path.read_text(encoding='utf-8'))
            if stored.get('version') == 1:
                if not isinstance(stored.get('config'), dict) or not isinstance(stored.get('encrypted_key'), str):
                    raise ValueError()
                config = dict(DEFAULTS, **stored['config'])
                self._validate(config)
                # Lazy in-memory migration: listing never rewrites credentials.
                provider = dict(id='legacy', name='默认提供商', config=config, encrypted_key=stored['encrypted_key'],
                                models=[{'id': config['model'], 'name': config['model']}])
                return dict(version=2, providers=[provider], active_id='legacy')
            if stored.get('version') != 2 or not isinstance(stored.get('providers'), list) or len(stored['providers']) > 30:
                raise ValueError()
            seen = set()
            for provider in stored['providers']:
                if not isinstance(provider, dict) or not isinstance(provider.get('id'), str) or not provider['id'] or len(provider['id']) > 128 or provider['id'] in seen:
                    raise ValueError()
                seen.add(provider['id'])
                self._name(provider.get('name'))
                if not isinstance(provider.get('config'), dict) or not isinstance(provider.get('encrypted_key'), str):
                    raise ValueError()
                config = dict(DEFAULTS, **provider['config'])
                self._validate(config, allow_empty_model=True)
                provider['config'] = config
                provider['models'] = self._models(provider.get('models'))
                if config['model'] and config['model'] not in {m['id'] for m in provider['models']}:
                    raise ValueError()
            active_id = stored.get('active_id')
            if active_id is not None:
                active = next((p for p in stored['providers'] if p['id'] == active_id), None)
                if active is None or not active['config']['model']:
                    raise ValueError()
            return dict(version=2, providers=stored['providers'], active_id=active_id)
        except (ValueError, OSError, TypeError, AttributeError, ProviderError):
            raise ProviderError('configuration', '连接配置无法读取，请重新保存设置') from None

    def _read(self):
        catalog = self._read_catalog()
        active = next((p for p in catalog['providers'] if p['id'] == catalog['active_id']), None)
        return active if active is not None else dict(config=dict(DEFAULTS), encrypted_key='')

    @staticmethod
    def _validate(config, allow_empty_model=False):
        if set(config) != set(DEFAULTS):
            raise ProviderError('validation', '连接配置包含未知字段')
        config['endpoint'] = _endpoint(config['endpoint'])
        model = config['model']
        if not isinstance(model, str) or (not model.strip() and not allow_empty_model) or len(model) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in model):
            raise ProviderError('validation', '请输入有效模型名称')
        config['model'] = model.strip()
        for key, (low, high) in LIMITS.items():
            if type(config[key]) is not int or not low <= config[key] <= high:
                raise ProviderError('validation', f'{key} 必须是 {low}–{high} 之间的整数')

    def get_public(self):
        with self.lock:
            stored = self._read()
            return dict(config=stored['config'], key_configured=bool(stored['encrypted_key']),
                        provider_id=stored.get('id'), provider_name=stored.get('name', ''))

    @staticmethod
    def _name(value):
        if not isinstance(value, str) or not value.strip() or len(value) > 80 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ProviderError('validation', '提供商名称须为 1–80 字且不含控制字符')
        return value.strip()

    @staticmethod
    def _models(values):
        if not isinstance(values, list) or len(values) > 500:
            raise ProviderError('validation', '模型目录必须是列表且最多包含 500 项')
        models, seen = [], set()
        for item in values:
            if not isinstance(item, dict) or set(item) - {'id', 'name'}:
                raise ProviderError('validation', '模型目录条目仅支持 id 和 name')
            model_id = item.get('id')
            name = item.get('name', model_id)
            if not all(isinstance(v, str) and v.strip() and len(v) <= 200 and not any(ord(c) < 32 or ord(c) == 127 for c in v) for v in (model_id, name)):
                raise ProviderError('validation', '模型 ID 和名称须为 1–200 字且不含控制字符')
            model_id, name = model_id.strip(), name.strip()
            if model_id not in seen:
                models.append({'id': model_id, 'name': name})
                seen.add(model_id)
        return models

    @staticmethod
    def _public_catalog(catalog):
        return dict(budget_limits=LIMITS,budget_defaults=BUDGET_DEFAULTS,active_id=catalog['active_id'], providers=[dict(id=p['id'], name=p['name'], config=copy.deepcopy(p['config']),
                    key_configured=bool(p['encrypted_key']), models=copy.deepcopy(p['models'])) for p in catalog['providers']])

    def _write_catalog(self, catalog):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent, delete=False) as handle:
                temporary = handle.name
                json.dump(catalog, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _encrypted_key(body, previous, endpoint):
        encrypted = previous['encrypted_key'] if previous['config']['endpoint'] == endpoint else ''
        if 'clear_key' in body and type(body['clear_key']) is not bool:
            raise ProviderError('validation', '清除密钥选项格式无效')
        if body.get('clear_key'):
            return ''
        if 'api_key' in body:
            key = body['api_key']
            if not isinstance(key, str) or len(key) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in key):
                raise ProviderError('validation', '密钥格式无效')
            return base64.b64encode(_crypt(key.encode())).decode('ascii') if key else ''
        return encrypted

    @staticmethod
    def _find(catalog, provider_id):
        if not isinstance(provider_id, str) or not provider_id or len(provider_id) > 128:
            raise ProviderError('not_found', '提供商不存在')
        provider = next((p for p in catalog['providers'] if p['id'] == provider_id), None)
        if provider is None:
            raise ProviderError('not_found', '提供商不存在')
        return provider

    def catalog(self, body):
        fields = {'list': set(), 'save': {'id', 'name', 'config', 'models', 'api_key', 'clear_key'},
                  'delete': {'id'}, 'activate': {'id', 'model'}, 'models': {'id'}, 'test': {'id'}}
        if not isinstance(body, dict) or not isinstance(body.get('action'), str) or body['action'] not in fields or set(body) - (fields[body['action']] | {'action'}):
            raise ProviderError('validation', '提供商操作格式无效')
        action = body['action']
        if action in {'models', 'test'}:
            with self.lock:
                provider = copy.deepcopy(self._find(self._read_catalog(), body.get('id')))
            # A manual discovery/test uses its own immutable connection snapshot.
            # It does not hold the settings lock or change the active provider.
            if action == 'models':
                return dict(models=self._fetch_models(provider), provider_id=provider['id'])
            return self._test_provider(provider)
        with self.lock:
            catalog = self._read_catalog()
            if action == 'list':
                return self._public_catalog(catalog)
            if action == 'save':
                previous = self._find(catalog, body['id']) if 'id' in body else None
                if previous is None and len(catalog['providers']) >= 30:
                    raise ProviderError('limit', '最多保存 30 个提供商')
                name = self._name(body.get('name', previous['name'] if previous else ''))
                changed = body.get('config', {})
                if not isinstance(changed, dict):
                    raise ProviderError('validation', '连接配置格式无效')
                config = dict(previous['config'] if previous else DEFAULTS, **changed)
                self._validate(config, allow_empty_model=True)
                models = self._models(body.get('models', previous['models'] if previous else []))
                if config['model'] and config['model'] not in {item['id'] for item in models}:
                    raise ProviderError('validation', '当前模型必须保留在模型目录中；删除前请同时选择另一个模型')
                if previous and previous['id'] == catalog['active_id'] and not config['model']:
                    raise ProviderError('validation', '当前提供商必须选择一个已保存的模型')
                encrypted = self._encrypted_key(body, previous or {'config': DEFAULTS, 'encrypted_key': ''}, config['endpoint'])
                provider = dict(id=previous['id'] if previous else uuid.uuid4().hex, name=name, config=config, models=models, encrypted_key=encrypted)
                if previous:
                    catalog['providers'][catalog['providers'].index(previous)] = provider
                else:
                    catalog['providers'].append(provider)
                if catalog['active_id'] is None and config['model']:
                    catalog['active_id'] = provider['id']
            else:
                provider = self._find(catalog, body.get('id'))
                if action == 'delete':
                    if provider['id'] == catalog['active_id'] or len(catalog['providers']) == 1:
                        raise ProviderError('conflict', '不能删除当前或最后一个提供商，请先切换到其他提供商')
                    catalog['providers'].remove(provider)
                elif action == 'activate':
                    model = body.get('model', provider['config']['model'])
                    if not isinstance(model, str) or model not in {item['id'] for item in provider['models']}:
                        raise ProviderError('validation', '请选择此提供商模型目录中的模型')
                    provider['config']['model'] = model
                    catalog['active_id'] = provider['id']
            self._write_catalog(catalog)
            return self._public_catalog(catalog)

    def configure(self, body):
        if isinstance(body, dict) and 'config' in body:
            if set(body) - {'config', 'api_key', 'clear_key'} or not isinstance(body['config'], dict):
                raise ProviderError('validation', '连接设置格式无效')
            body = dict(body['config'], **{k: body[k] for k in ('api_key', 'clear_key') if k in body})
        if isinstance(body, dict) and 'clear_key' in body:
            body = dict(body)
            clear = body.pop('clear_key')
            if type(clear) is not bool:
                raise ProviderError('validation', '清除密钥选项格式无效')
            if clear:
                body['api_key'] = ''
        if not isinstance(body, dict) or set(body) - (set(DEFAULTS) | {'api_key'}):
            raise ProviderError('validation', '连接设置格式无效')
        with self.lock:
            catalog = self._read_catalog()
            active = next((p for p in catalog['providers'] if p['id'] == catalog['active_id']), None)
            old = active or dict(config=dict(DEFAULTS), encrypted_key='')
            config = dict(old['config'], **{k: v for k, v in body.items() if k in DEFAULTS})
            self._validate(config)
            encrypted = self._encrypted_key(body, old, config['endpoint'])
            if active is None:
                if len(catalog['providers']) >= 30:
                    raise ProviderError('limit', '最多保存 30 个提供商')
                active = dict(id=uuid.uuid4().hex, name='默认提供商', models=[])
                catalog['providers'].append(active)
                catalog['active_id'] = active['id']
            if config['model'] not in {item['id'] for item in active['models']}:
                if len(active['models']) >= 500:
                    raise ProviderError('limit', '模型目录已达到 500 项上限')
                active['models'].append({'id': config['model'], 'name': config['model']})
            active.update(config=config, encrypted_key=encrypted)
            self._write_catalog(catalog)
            return dict(config=config, key_configured=bool(encrypted), provider_id=active['id'], provider_name=active['name'])

    def _fetch_models(self, provider):
        """GET only the selected provider's same-origin sibling /models."""
        parts = urlsplit(provider['config']['endpoint'])
        route = parts.path.removesuffix('/chat/completions') + '/models'
        host = '127.0.0.1' if parts.hostname.lower() == 'localhost' else parts.hostname
        timeout = min(60, provider['config']['timeout'])
        deadline = time.monotonic() + timeout
        connection_type = http.client.HTTPSConnection if parts.scheme == 'https' else http.client.HTTPConnection
        conn = connection_type(host, parts.port, timeout=timeout)
        response, active_socket = None, None
        def expire():
            sock = conn.sock or active_socket
            if sock is None and response is not None:
                sock = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
            if sock:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    descriptor = sock.detach()
                    if descriptor != -1:
                        socket.close(descriptor)
                except OSError:
                    pass
            conn.close()
        def check():
            if time.monotonic() >= deadline:
                raise ProviderError('timeout', '获取模型列表超时；可重试或手动添加模型 ID')
        timer = threading.Timer(timeout, expire)
        timer.daemon = True
        timer.start()
        try:
            headers = {'Accept': 'application/json'}
            key = self._key(provider)
            if key:
                headers['Authorization'] = 'Bearer ' + key
            conn.request('GET', route, headers=headers)
            active_socket = conn.sock
            check()
            response = conn.getresponse()
            if 300 <= response.status < 400:
                raise ProviderError('redirect', '模型目录返回重定向，未继续发送密钥；请检查端点或手动添加模型')
            if response.status in {404, 405, 501}:
                raise ProviderError('unsupported', '此提供商不支持获取模型目录，请手动添加模型 ID')
            if response.status != 200:
                raise ProviderError('http_error', f'获取模型目录失败（HTTP {response.status}）；请检查连接或手动添加模型')
            raw = response.read(2 * 1024 * 1024 + 1)
            check()
            if len(raw) > 2 * 1024 * 1024:
                raise ProviderError('limit', '模型目录响应超过 2 MiB；请手动添加需要的模型')
            try:
                payload = json.loads(raw)
                if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
                    raise ValueError()
            except (ValueError, UnicodeError):
                raise ProviderError('protocol', '提供商未返回支持的模型列表格式，请手动添加模型 ID') from None
            models, seen = [], set()
            for item in payload['data']:
                if not isinstance(item, dict):
                    continue
                model_id = item.get('id')
                try:
                    model = self._models([{'id': model_id, 'name': item.get('name') or model_id}])[0]
                except ProviderError:
                    continue
                if model['id'] not in seen:
                    seen.add(model['id'])
                    models.append(model)
                    if len(models) == 500:
                        break
            return models
        except ProviderError:
            raise
        except (OSError, http.client.HTTPException, UnicodeError, ValueError):
            check()
            raise ProviderError('connection', '无法获取模型目录，请检查连接或手动添加模型 ID') from None
        finally:
            timer.cancel()
            if response:
                response.close()
            conn.close()
            timer.join(timeout=0.2)

    def stream_completion(self, messages, tools=None, cancel_event=None, deadline=None):
        with self.lock:
            stored = self._read()
        yield from self._stream_with(stored, messages, tools, cancel_event, deadline)

    @staticmethod
    def _key(stored):
        try:
            return _crypt(base64.b64decode(stored['encrypted_key'], validate=True), decrypt=True).decode() if stored['encrypted_key'] else ''
        except (ValueError, UnicodeError):
            raise ProviderError('credential_storage', '连接密钥无法解密，请重新填写') from None

    def _stream_with(self, stored, messages, tools=None, cancel_event=None, deadline=None):
        with self.lock:
            config = stored['config']
            self._validate(config)
            key = self._key(stored)
        cancel_event = cancel_event or threading.Event()
        deadline = min(deadline if deadline is not None else float('inf'), time.monotonic() + config['timeout'])
        def check():
            if cancel_event.is_set():
                raise ProviderError('cancelled', '请求已取消')
            if time.monotonic() >= deadline:
                raise ProviderError('timeout', '模型请求超时')
        check()
        payload = dict(model=config['model'], messages=messages, stream=True,
                       stream_options={'include_usage': True}, max_completion_tokens=config['max_output_tokens'])
        if tools:
            payload.update(tools=tools, tool_choice='auto')
        try:
            raw = json.dumps(payload, ensure_ascii=False).encode()
        except (TypeError, ValueError):
            raise ProviderError('validation', '模型请求格式无效') from None
        if len(raw) > 2 * 1024 * 1024:
            raise ProviderError('limit', '模型请求内容超过大小上限')
        parts = urlsplit(config['endpoint'])
        # localhost is pinned to the loopback address, never resolved remotely.
        host = '127.0.0.1' if parts.hostname.lower() == 'localhost' else parts.hostname
        connection_type = http.client.HTTPSConnection if parts.scheme == 'https' else http.client.HTTPConnection
        conn = connection_type(host, parts.port, timeout=max(0.01, deadline - time.monotonic()))
        finished = threading.Event()
        response = None
        active_socket = None
        def guard():
            while not finished.wait(0.05):
                if cancel_event.is_set() or time.monotonic() >= deadline:
                    sock = conn.sock or active_socket
                    if sock is None and response is not None:
                        sock = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
                    if sock:
                        try:
                            sock.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                        # HTTP/1.0 hands socket ownership to response.makefile().
                        # socket.close() then defers actual closure; detach closes
                        # that Windows handle now and invalidates all wrappers.
                        try:
                            descriptor = sock.detach()
                            if descriptor != -1:
                                socket.close(descriptor)
                        except OSError:
                            pass
                    conn.close()
                    return
        watcher = threading.Thread(target=guard, daemon=True)
        watcher.start()
        try:
            headers = {'Content-Type': 'application/json', 'Accept': 'text/event-stream'}
            if key:
                headers['Authorization'] = 'Bearer ' + key
            conn.request('POST', parts.path, body=raw, headers=headers)
            active_socket = conn.sock
            check()
            response = conn.getresponse()
            if 300 <= response.status < 400:
                raise ProviderError('redirect', '模型端点返回重定向；请填写最终地址后重试')
            if response.status != 200:
                raise ProviderError('http_error', f'模型请求失败（HTTP {response.status}）')
            if 'text/event-stream' not in response.getheader('Content-Type', '').lower():
                raise ProviderError('protocol', '模型端点未返回 SSE 流式响应')
            calls, reason, total, data_lines, done = {}, None, 0, [], False
            while True:
                check()
                line = response.readline(1024 * 1024 + 1)
                check()
                total += len(line)
                if len(line) > 1024 * 1024 or total > 8 * 1024 * 1024:
                    raise ProviderError('limit', '模型响应超过大小上限')
                if not line:
                    break
                try:
                    line = line.decode('utf-8').rstrip('\r\n')
                except UnicodeError:
                    raise ProviderError('protocol', '模型响应编码无效') from None
                if line.startswith('data:'):
                    data_lines.append(line[5:].lstrip(' '))
                    continue
                if line or not data_lines:
                    continue
                data = '\n'.join(data_lines)
                data_lines = []
                if data == '[DONE]':
                    done = True
                    break
                try:
                    chunk = json.loads(data)
                    if not isinstance(chunk, dict):
                        raise ValueError()
                    if chunk.get('error'):
                        raise ProviderError('remote_error', '模型服务返回错误，请检查连接设置后重试')
                    usage = chunk.get('usage')
                    if isinstance(usage, dict):
                        safe_usage = {k: usage[k] for k in ('prompt_tokens', 'completion_tokens', 'total_tokens') if type(usage.get(k)) is int and usage[k] >= 0}
                        yield dict(type='usage', usage=safe_usage)
                    for choice in chunk.get('choices', []):
                        if choice.get('index', 0) != 0:
                            continue
                        reason = choice.get('finish_reason') or reason
                        delta = choice.get('delta') or {}
                        content = delta.get('content')
                        if content is not None:
                            if not isinstance(content, str):
                                raise ValueError()
                            if content:
                                yield dict(type='text', text=content)
                        for call in delta.get('tool_calls') or []:
                            index = call['index']
                            if type(index) is not int or index < 0 or index >= config['max_tool_calls']:
                                raise ProviderError('limit', '模型工具调用超过数量上限')
                            aggregate = calls.setdefault(index, dict(id='', name='', arguments=''))
                            function = call.get('function') or {}
                            for field, value in [('id', call.get('id')), ('name', function.get('name')), ('arguments', function.get('arguments'))]:
                                if value is not None:
                                    if not isinstance(value, str):
                                        raise ValueError()
                                    aggregate[field] += value
                            if sum(len(v) for v in aggregate.values()) > 128 * 1024:
                                raise ProviderError('limit', '模型工具参数超过大小上限')
                except (ValueError, TypeError, KeyError, AttributeError):
                    raise ProviderError('protocol', '模型流式响应格式无效') from None
            if not done or not reason:
                raise ProviderError('incomplete', '模型响应中断，未收到完整结束标记')
            if calls and reason != 'tool_calls':
                raise ProviderError('incomplete', '工具调用未完整结束，未执行任何工具')
            for index in sorted(calls):
                call = calls[index]
                try:
                    if not call['id'] or not call['name'] or not isinstance(json.loads(call['arguments']), dict):
                        raise ValueError()
                except (ValueError, TypeError):
                    raise ProviderError('protocol', '模型工具调用参数无效') from None
            check()
            for index in sorted(calls):
                yield dict(type='tool_call', **calls[index])
            yield dict(type='done', finish_reason=reason)
        except ProviderError:
            raise
        except (OSError, http.client.HTTPException, UnicodeError, ValueError):
            check()
            raise ProviderError('connection', '无法完成模型连接，请检查端点、网络和密钥') from None
        finally:
            finished.set()
            if response:
                response.close()
            conn.close()
            watcher.join(timeout=0.2)

    complete_stream = stream_completion

    def test_connection(self, cancel_event=None):
        with self.lock:
            provider = self._read()
        return self._test_provider(provider, cancel_event)

    def _test_provider(self, provider, cancel_event=None):
        usage = None
        for event in self._stream_with(provider, [{'role': 'user', 'content': 'Reply with OK.'}], cancel_event=cancel_event):
            if event['type'] == 'usage':
                usage = event['usage']
        return dict(ok=True, model=provider['config']['model'], usage=usage, provider_id=provider.get('id'))
