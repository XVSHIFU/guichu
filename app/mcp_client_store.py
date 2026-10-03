"""Explicit Local Desk MCP registrations; never imports inventory/host config.

Commands execute user-installed code, not a sandbox. enabled + allowed_tools is
the user's persistent permission to call reviewed read-only tools in a session.
Annotations alone grant no permission. Credentials are encrypted with Windows DPAPI and never returned by settings. Model-facing code receives immutable per-run registration snapshots.
"""
import base64
import ipaddress
from urllib.parse import urlsplit
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

MAX_SERVERS = 12


def initialize(connection):
    with connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS mcp_clients (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')


def list_servers(connection):
    with connection() as db:
        return [json.loads(row[0]) for row in db.execute('SELECT payload FROM mcp_clients ORDER BY id')]


def get_server(connection, server_id):
    return next((item for item in list_servers(connection) if item['id'] == server_id), None)


def local_path(value, directory=False):
    if not isinstance(value, str) or not value or len(value) > 2048 or '\x00' in value:
        raise ValueError('路径无效')
    path = Path(value)
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise ValueError('仅支持本机绝对路径')
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink() or (hasattr(ancestor, 'is_junction') and ancestor.is_junction()):
            raise ValueError('不支持链接路径')
    if not (path.is_dir() if directory else path.is_file()):
        raise ValueError('登记路径不存在或类型不符')
    if not directory and os.name == 'nt' and path.suffix.lower() != '.exe':
        raise ValueError('启动命令必须是可执行文件，不接受 shell 或批处理字符串')
    if not directory and path.stem.lower() in {'cmd', 'powershell', 'pwsh', 'bash', 'sh', 'wscript', 'cscript'}:
        raise ValueError('不支持 shell 启动器')
    return str(path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def remote_url(value):
    if not isinstance(value, str) or len(value)>2048 or any(ord(c)<33 for c in value):
        raise ValueError('服务地址无效')
    try:
        parts=urlsplit(value)
        parts.port
        if parts.scheme not in {'https','http'} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError()
        if parts.scheme=='http' and parts.hostname!='localhost' and not ipaddress.ip_address(parts.hostname).is_loopback:
            raise ValueError()
        value.encode('ascii')
    except (ValueError,UnicodeError):
        raise ValueError('仅支持 HTTPS 或本机回环 HTTP；地址不能包含账号、查询参数或片段') from None
    return value


def public_server(record):
    return {**{k:v for k,v in record.items() if k!='credential'}, 'has_token':bool(record.get('credential'))}


def authorization(record):
    if not record.get('credential'):
        return {}
    from model_provider import _crypt
    return {'Authorization':'Bearer '+_crypt(base64.b64decode(record['credential']),decrypt=True).decode('utf-8')}


def save(connection, body):
    fields = {'id', 'name', 'command', 'args', 'cwd', 'enabled', 'allowed_tools', 'acknowledge_execution', 'transport', 'url', 'token', 'clear_token'}
    if set(body) - fields or body.get('acknowledge_execution') is not True:
        raise ValueError('请明确确认启动此程序，并只提供支持的登记字段')
    server_id = body.get('id') or uuid.uuid4().hex
    if not isinstance(server_id, str) or not re.fullmatch('[a-f0-9]{32}', server_id):
        raise ValueError('服务 ID 无效')
    old = get_server(connection, server_id)
    name, args, allowed = body.get('name'), body.get('args', []), body.get('allowed_tools', [])
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise ValueError('服务名称不能为空或超过100字符')
    if not isinstance(args, list) or len(args) > 64 or any(not isinstance(a, str) or len(a) > 2048 or '\x00' in a for a in args):
        raise ValueError('参数必须是有界字符串数组')
    if not isinstance(allowed, list) or len(allowed) > 100 or any(not isinstance(a, str) or len(a) > 128 for a in allowed):
        raise ValueError('允许工具列表无效')
    if type(body.get('enabled', False)) is not bool:
        raise ValueError('enabled 必须为布尔值')
    transport=body.get('transport','stdio')
    if transport not in {'stdio','streamable-http'}:
        raise ValueError('不支持的连接方式')
    record = {'id':server_id,'name':name.strip(),'transport':transport,'enabled':body.get('enabled',False),
              'allowed_tools':list(dict.fromkeys(allowed)),'tools':[], 'revision':(old or {}).get('revision',0)+1}
    if transport=='stdio':
        record.update(command=local_path(body.get('command')),args=args,cwd=local_path(body.get('cwd'),True))
    else:
        token=body.get('token','')
        if not isinstance(token,str) or len(token)>8192 or any(ord(c)<33 or ord(c)>126 for c in token):
            raise ValueError('访问令牌格式无效')
        if type(body.get('clear_token',False)) is not bool:
            raise ValueError('clear_token 必须为布尔值')
        record['url']=remote_url(body.get('url'))
        # Never carry credentials across a change of destination.
        record['credential']=(old or {}).get('credential','') if (old or {}).get('url')==record['url'] else ''
        if body.get('clear_token'):
            record['credential']=''
        if token:
            from model_provider import _crypt
            record['credential']=base64.b64encode(_crypt(token.encode('utf-8'))).decode('ascii')
    same_command = old and old.get('transport','stdio')==transport and all(old.get(key)==record.get(key) for key in ('command','args','cwd','url','credential'))
    if same_command:
        record['tools'] = old.get('tools', [])
    names = {tool['name'] for tool in record['tools'] if tool.get('readOnlyHint') is True}
    if set(allowed) - names or (record['enabled'] and not allowed):
        raise ValueError('请先显式发现工具，再选择已审核的只读工具后启用')
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        current = db.execute('SELECT payload FROM mcp_clients WHERE id=?', (server_id,)).fetchone()
        if (json.loads(current[0]) if current else None) != old:
            raise ValueError('登记已变化，请刷新后重试')
        if not old and db.execute('SELECT COUNT(*) FROM mcp_clients').fetchone()[0] >= MAX_SERVERS:
            raise ValueError('登记服务数量已达上限')
        db.execute('INSERT OR REPLACE INTO mcp_clients VALUES (?,?)', (server_id, json.dumps(record, ensure_ascii=False)))
    return record


def dispatch(connection, route, body):
    from mcp_client import discover
    try:
        if not isinstance(body, dict):
            raise ValueError('请求必须是对象')
        action = route.removeprefix('/api/mcp-client/')
        if action == 'list' and not body:
            return {'servers': [public_server(s) for s in list_servers(connection)]}, 200
        if action == 'save':
            return {'server': public_server(save(connection, body))}, 200
        expected = {'id', 'acknowledge_execution'} if action == 'discover' else {'id'}
        if action not in {'discover', 'delete'} or set(body) != expected:
            raise ValueError('不支持的请求')
        if action == 'discover' and body.get('acknowledge_execution') is not True:
            raise ValueError('发现工具会启动程序，请先明确确认')
        server = get_server(connection, body['id'])
        if not server:
            return {'error': '服务不存在'}, 404
        if action == 'delete':
            with connection() as db:
                db.execute('DELETE FROM mcp_clients WHERE id=?', (server['id'],))
            return {'deleted': True}, 200
        result = discover(server)
        if not result['ok']:
            code = result['error']['code']
            message = {'timeout': '发现超时，服务进程已进入清理流程', 'cancelled': '发现已取消',
                       'catalog_limit': '工具目录超过限制，未保存', 'connection_failed': '无法连接此服务，请检查地址、认证或启动参数'}.get(code, '工具目录不受支持，未保存')
            return {'error': message, 'code': code}, 400
        with connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload FROM mcp_clients WHERE id=?', (server['id'],)).fetchone()
            if not row or json.loads(row[0]) != server:
                raise ValueError('发现期间登记已变化，请重新发现')
            # A new discovery invalidates prior approval, even if names match.
            server.update(tools=result['data']['tools'], enabled=False, allowed_tools=[], revision=server['revision'] + 1)
            db.execute('UPDATE mcp_clients SET payload=? WHERE id=?', (json.dumps(server, ensure_ascii=False), server['id']))
        return {'server': public_server(server), 'tools': server['tools']}, 200
    except ValueError as error:
        return {'error': str(error)}, 400
