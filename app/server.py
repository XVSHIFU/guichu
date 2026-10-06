"""Local-only inventory and confirmed fixed actions; no arbitrary shell endpoint."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import threading
import time
import tomllib
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

import psutil
import yaml
from local_icons import enrich_icons, CACHE
import file_actions
import assistant_store
import assistant_runtime
import action_store
import mcp_action_store
import directory_sizes
import scan_tasks
import relation_store
import source_registry
import action_origin
import cleanup_store
from registered_sources import collect_registered
from package_inventory import collect_packages
from software_locations import automatic_sources, enrich_locations
import software_origin
import system_components
from windows_apps import collect_windows_apps
from manager_inventory import collect_managers
from tool_identity import enrich as enrich_tool_identity
import assistant_tools
import agent_preferences
import mcp_client_store
import mcp_client
from model_provider import ModelProvider, ProviderError
from snapshot_state import reconcile

ROOT = Path(__file__).resolve().parent
HOME = Path.home()
DB = ROOT / 'data' / 'workbench.sqlite3'
PROVIDER = ModelProvider(ROOT/'data')
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.Lock()
def agent_context():
    return {'config_path':HOME/'.codex/config.toml','claude_config_path':HOME/'.claude.json','backup_dir':ROOT/'data'/'config-backups',
            'preferences':agent_preferences.read(connection),
            'mcp_registry':mcp_client.Registry(connection,server_ids=[s['id'] for s in mcp_client_store.list_servers(connection) if s['enabled']])}

def scan_status():return scan_tasks.status(connection)
CATEGORIES={'办公与协作','游戏与平台','开发工具','开发环境','网络与远程','影音与创作','系统与驱动','其他软件'}
REQUEST_LOCK=threading.RLock()
SERVICE={'requests':0,'stopping':False}

def busy_reasons():
    reasons=[]
    if scan_status()['running']:reasons.append('清单检查正在进行')
    with assistant_runtime.LOCK:
        if assistant_runtime.ACTIVE:reasons.append('助手正在分析')
    if directory_sizes.is_running():reasons.append('目录统计正在进行')
    with connection() as db:
        if any(json.loads(row[0]).get('state') in ['applying','restoring'] for row in db.execute('SELECT payload FROM mcp_actions')):reasons.append('配置正在写入或恢复')
        if any(json.loads(row[0]).get('state')=='executing' for row in db.execute('SELECT payload FROM cleanup_actions')):reasons.append('回收或卸载启动操作正在进行')
    return reasons

def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')

def identity(kind, value):
    return kind + ':' + hashlib.sha256(str(value).casefold().encode()).hexdigest()[:16]

@contextmanager
def connection():
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    try:
        with c:
            yield c
    finally:
        c.close()

def initialize():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connection() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS scans(id INTEGER PRIMARY KEY, at TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS notes(id TEXT PRIMARY KEY, decision TEXT, body TEXT, updated TEXT);
        CREATE TABLE IF NOT EXISTS changes(id INTEGER PRIMARY KEY, at TEXT, object_id TEXT, name TEXT, kind TEXT, event TEXT);
        CREATE TABLE IF NOT EXISTS tool_identities(object_id TEXT PRIMARY KEY,value TEXT NOT NULL,updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS categories(object_id TEXT PRIMARY KEY,value TEXT NOT NULL,updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS software_origins(object_id TEXT PRIMARY KEY,value TEXT NOT NULL,updated TEXT NOT NULL);''')
    assistant_store.initialize(connection)
    mcp_client_store.initialize(connection)
    agent_preferences.initialize(connection)
    assistant_runtime.initialize(connection)
    action_store.initialize(connection)
    mcp_action_store.initialize(connection)
    directory_sizes.initialize(connection)
    scan_tasks.initialize(connection)
    relation_store.initialize(connection)
    source_registry.initialize(connection)
    cleanup_store.initialize(connection)

from inventory import collect

def latest():
    with connection() as c:
        row=c.execute('SELECT payload FROM scans ORDER BY id DESC LIMIT 1').fetchone()
        data=json.loads(row[0]) if row else None
        notes={r['id']:dict(r) for r in c.execute('SELECT * FROM notes')}
        changes=[dict(r) for r in c.execute('SELECT * FROM changes ORDER BY id DESC LIMIT 100')]
        identities={r['object_id']:r['value'] for r in c.execute('SELECT * FROM tool_identities')}
        categories={r['object_id']:r['value'] for r in c.execute('SELECT * FROM categories')}
        origins={r['object_id']:json.loads(r['value']) for r in c.execute('SELECT * FROM software_origins')}
    if data:
        data['notes']=notes;data['changes']=changes
        for obj in data.get('objects',[]):
            software_origin.enrich(obj,origins.get(obj['id']))
            system_components.enrich(obj)
            if obj['id'] in categories:obj['manualCategory']=categories[obj['id']]
            if obj['id'] in identities:
                obj['manualIdentity']=identities[obj['id']]
                obj['capabilities']=['software','agent'] if identities[obj['id']]=='agent' else ['software']
                obj['agentIdentity']='user_defined'
                obj['identityEvidence']='用户手动标记；不表示已验证运行状态或工具能力。'
    return relation_store.overlay(data,connection) if data else data

def scan_collect():
    data=collect()
    registrations=source_registry.list_sources(connection)
    registrations += list(automatic_sources(data.get('disks',[])))
    registered=collect_registered([s for s in registrations if s['type'] in ('portable','project')])
    packages=collect_packages(registrations)
    windows_apps=collect_windows_apps(data['at'])
    managers=collect_managers()
    for key in ['objects','relations','issues','sources']:
        packages.setdefault(key,[]).extend(managers.get(key,[]))
    for key in ['objects','relations','issues','sources']:
        packages.setdefault(key,[]).extend(windows_apps.get(key,[]))
    for key in ['objects','relations','issues','sources']:
        registered.setdefault(key,[]).extend(packages.get(key,[]))
    for key in ['objects','relations','issues','sources']:
        data.setdefault(key,[]).extend(registered.get(key,[]))
    data['scope']='Windows 注册表、常见安装与数据目录、登记目录及 PATH / 当前 Python 环境中的命令包；限量检查，不含全部自定义位置、WSL 或云端插件。'
    with connection() as c:
        previous=c.execute('SELECT payload FROM scans ORDER BY id DESC LIMIT 1').fetchone()
        if previous:
            previous_data=json.loads(previous[0])
            data=reconcile(previous_data,data)
            old={o['id']:o for o in previous_data['objects']}
            new={o['id']:o for o in data['objects']}
            for oid in new.keys()|old.keys():
                event='新增' if oid not in old else '已移除' if oid not in new and (bool(data.get('sources')) or not data['issues']) else None
                if oid not in new:
                    if event:
                        o=old[oid];c.execute('INSERT INTO changes(at,object_id,name,kind,event) VALUES (?,?,?,?,?)',(data['at'],oid,o['name'],o['kind'],event))
                    continue
                if not event:
                    fields=['path','version','enabled','commandExists']
                    if any(old[oid].get(k)!=new[oid].get(k) for k in fields):event='配置变化'
                if event:
                    o=new.get(oid,old.get(oid));c.execute('INSERT INTO changes(at,object_id,name,kind,event) VALUES (?,?,?,?,?)',(data['at'],oid,o['name'],o['kind'],event))
        enrich_locations(data)
        enrich_tool_identity(data)
        try:enrich_icons(data['objects'])
        except Exception:data['issues'].append({'sourceKey':'icons','name':'软件图标','reason':'图标读取失败'})
        c.execute('INSERT INTO scans(at,payload) VALUES (?,?)',(data['at'],json.dumps(data,ensure_ascii=False)))
        c.execute('DELETE FROM scans WHERE id NOT IN (SELECT id FROM scans ORDER BY id DESC LIMIT 20)')
    return data

def scan():
    return scan_tasks.start(connection,scan_collect)

from directory_browser import browse_directory

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def json_response(self,payload,status=200):
        raw=json.dumps(payload,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw)
    def valid_host(self):
        return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
    def do_GET(self):
        if not self.valid_host():return self.json_response({'error':'无效来源'},403)
        route=urlparse(self.path).path
        if route=='/api/state':return self.json_response({'data':latest(),'scan':scan_status(),'scan_history':scan_tasks.list_tasks(connection),'token':TOKEN})
        if route=='/api/health':
            reasons=busy_reasons()
            return self.json_response({'app':'local-desk','ok':True,'pid':os.getpid(),'server_path':str(Path(__file__).resolve()),'busy':bool(reasons) or SERVICE['requests']>0,'busy_reasons':reasons})
        if route=='/api/vitals':
            mem=psutil.virtual_memory()
            return self.json_response({'cpu':psutil.cpu_percent(),'memory':mem.percent,'memoryUsed':mem.used,'memoryTotal':mem.total,'at':now()})
        if route.startswith('/local-icons/'):
            filename=route.removeprefix('/local-icons/')
            if len(filename)!=28 or not filename.endswith('.png') or any(c not in '0123456789abcdef' for c in filename[:-4]):return self.json_response({'error':'Not found'},404)
            path=CACHE/filename
        elif route.startswith('/archive/'):
            archive=(ROOT.parent/'local-archive').resolve()
            path=(archive/unquote(route[len('/archive/'):])).resolve()
            if path.parent != archive or path.suffix not in {'.html','.css','.js','.md'}:return self.json_response({'error':'Not found'},404)
        else:
            base=ROOT/'dist';path=(base/unquote(route.lstrip('/'))).resolve()
            if not path.is_relative_to(base.resolve()):return self.json_response({'error':'Not found'},404)
            if not path.is_file():path=base/'index.html'
        try: raw=path.read_bytes()
        except OSError:return self.json_response({'error':'页面未构建，请先执行 npm run build'},404)
        self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(path)[0] or 'application/octet-stream');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'");self.end_headers();self.wfile.write(raw)
    def do_POST(self):
        with REQUEST_LOCK:
            if SERVICE['stopping']:return self.json_response({'error':'服务正在停止'},503)
            SERVICE['requests']+=1
        try:return self.handle_post()
        finally:
            with REQUEST_LOCK:SERVICE['requests']-=1
    def handle_post(self):
        origin=self.headers.get('Origin')
        allowed={f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'}
        if not self.valid_host() or origin not in allowed or self.headers.get('X-Desk-Token')!=TOKEN:return self.json_response({'error':'操作来源校验失败'},403)
        try:
            size=int(self.headers.get('Content-Length','0'))
            limit=65536 if urlparse(self.path).path=='/api/agent/preferences' else 16000
            if not 0<=size<=limit:raise ValueError()
            body=json.loads(self.rfile.read(size) or b'{}')
            if not isinstance(body,dict):raise ValueError()
        except (ValueError,TypeError):return self.json_response({'error':'无效请求'},400)
        route=urlparse(self.path).path
        if route=='/api/file-action':
            result,status=file_actions.dispatch(body)
            return self.json_response(result,status)
        if route=='/api/shutdown':
            with REQUEST_LOCK:
                reasons=busy_reasons()
                if SERVICE['requests']>1:reasons.append('另有请求正在处理')
                if reasons:return self.json_response({'error':'暂不能停止：'+'；'.join(reasons)},409)
                SERVICE['stopping']=True
            self.json_response({'ok':True})
            threading.Thread(target=self.server.shutdown,daemon=True).start()
            return
        if route.startswith('/api/model/'):
            try:
                if route=='/api/model/catalog':
                    command=body.get('action') if isinstance(body,dict) else None
                    if isinstance(command,str) and command in {'save','delete','activate'}:
                        with assistant_runtime.LOCK:
                            if assistant_runtime.ACTIVE:return self.json_response({'error':'请等待运行任务结束再修改模型连接'},409)
                            result=PROVIDER.catalog(body)
                    else:
                        result=PROVIDER.catalog(body)
                    return self.json_response(result)
                if route=='/api/model/settings':
                    with assistant_runtime.LOCK:
                        if body and assistant_runtime.ACTIVE:return self.json_response({'error':'请等待运行任务结束再修改模型连接'},409)
                        result=PROVIDER.configure(body) if body else PROVIDER.get_public()
                    return self.json_response(result)
                if route=='/api/model/test':return self.json_response(PROVIDER.test_connection())
                return self.json_response({'error':'接口不存在'},404)
            except (ProviderError,ValueError) as exc:return self.json_response({'error':str(exc)},400)
        if route.startswith('/api/relation/'):
            try:payload,status=relation_store.dispatch(connection,route,body,(latest() or {}).get('objects',[]))
            except sqlite3.Error:return self.json_response({'error':'关联保存失败，请重试'},500)
            return self.json_response(payload,status)
        if route.startswith('/api/source/'):
            try:payload,status=source_registry.dispatch(connection,route,body)
            except sqlite3.Error:return self.json_response({'error':'来源登记保存失败，请重试'},500)
            return self.json_response(payload,status)
        if route.startswith('/api/cleanup/'):
            if route=='/api/cleanup/open-bin':
                try:os.startfile('shell:RecycleBinFolder')
                except OSError:return self.json_response({'error':'无法打开回收站，请从桌面打开'},500)
                return self.json_response({'ok':True})
            data=latest() or {}
            objects=[{**obj,'retention':data.get('notes',{}).get(obj['id'],{}).get('decision')} for obj in data.get('objects',[])]
            protected=[ROOT,HOME/'.codex',HOME/'.agents',HOME/'.ssh']
            try:payload,status=cleanup_store.dispatch(connection,route,body,objects,protected)
            except sqlite3.Error:return self.json_response({'error':'操作记录保存失败，请先重新读取历史核对结果'},500)
            if status==200 and route.rsplit('/',1)[-1] in ['confirm','verify']:scan()
            return self.json_response(payload,status)
        if route.startswith('/api/size/'):
            payload,status=directory_sizes.dispatch(connection,route,body)
            return self.json_response(payload,status)
        if route.startswith('/api/action/'):
            try:payload,status=action_store.dispatch(connection,route,body,(latest() or {}).get('objects',[]))
            except sqlite3.Error:return self.json_response({'error':'标记记录保存失败，事务已撤销，请重试'},500)
            return self.json_response(payload,status)
        if route.startswith('/api/mcp-action/'):
            try:
                payload,status=mcp_action_store.dispatch(connection,route,body,(latest() or {}).get('objects',[]),HOME/'.codex/config.toml',ROOT/'data'/'config-backups')
                if status==200 and route.rsplit('/',1)[-1] in ['confirm','restore']:scan()
            except sqlite3.Error:return self.json_response({'error':'操作记录保存失败，请重新读取记录后再试'},500)
            return self.json_response(payload,status)
        if route.startswith('/api/mcp-client/'):
            try:payload,status=mcp_client_store.dispatch(connection,route,body)
            except sqlite3.Error:return self.json_response({'error':'连接登记保存失败，请重试'},500)
            if status>=400 and isinstance(payload.get('error'),dict):payload={'error':'MCP连接失败：'+str(payload['error'].get('code','unknown'))}
            return self.json_response(payload,status)
        if route in ['/api/agent/confirm','/api/agent/reject','/api/agent/command']:
            if route.endswith('/confirm'):
                payload,status=assistant_runtime.confirm_proposal(connection,body,latest() or {},PROVIDER,assistant_tools,agent_context())
                if status==200:scan()
            elif route.endswith('/reject'):payload,status=assistant_runtime.reject_proposal(connection,body,latest() or {},agent_context())
            else:payload,status=assistant_runtime.command(connection,body)
            return self.json_response(payload,status)
        if route=='/api/agent/preferences':
            payload,status=agent_preferences.dispatch(connection,body)
            return self.json_response(payload,status)
        if route.startswith('/api/run/'):
            if route=='/api/run/start':payload,status=assistant_runtime.start(connection,body,latest() or {},PROVIDER,assistant_tools,agent_context())
            elif route=='/api/run/get':
                try:after=max(0,int(body.get('after',0)))
                except (ValueError,TypeError):return self.json_response({'error':'事件序号无效'},400)
                payload,status=assistant_runtime.get(connection,body.get('id',''),after)
            elif route=='/api/run/cancel':payload,status=assistant_runtime.cancel_run(connection,body.get('id',''))
            else:payload,status={'error':'接口不存在'},404
            return self.json_response(payload,status)
        if route=='/api/assistant/actions':
            sid=body.get('id')
            if not isinstance(sid,str) or not sid.strip() or len(sid)>128:
                return self.json_response({'error':'会话 ID 无效'},400)
            try:return self.json_response({'actions':action_origin.list_for_session(connection,sid)})
            except sqlite3.Error:return self.json_response({'error':'操作记录读取失败，请重试'},500)
        if route.startswith('/api/assistant/'):
            try:
                with assistant_runtime.LOCK:
                    if route.rsplit('/',1)[-1] in ['delete','send'] or (route.endswith('/update') and ('target_id' in body or 'target_ids' in body)):
                        with connection() as db:
                            records=db.execute('SELECT payload FROM assistant_runs WHERE session_id=?',(body.get('id',''),)).fetchall()
                        if any(json.loads(r[0])['status'] not in assistant_runtime.TERMINAL for r in records):return self.json_response({'error':'此会话仍在运行，请先停止任务'},409)
                    payload,status=assistant_store.dispatch(connection,route,body,(latest() or {}).get('objects',[]))
                return self.json_response(payload,status)
            except sqlite3.Error:
                return self.json_response({'error':'会话保存失败，请重试；原有记录未被覆盖'},500)
        if route=='/api/browse':
            payload,status=browse_directory(body)
            return self.json_response(payload,status)
        if route=='/api/scan':return self.json_response({'started':scan()})
        data=latest()
        obj=next((o for o in (data or {}).get('objects',[]) if o['id']==body.get('id')),None)
        if not obj:return self.json_response({'error':'对象不存在，请刷新清单'},404)
        if route=='/api/software-origin':
            value=body.get('value')
            if obj['kind'] not in ('software','agent') or not software_origin.valid_override(value):return self.json_response({'error':'来源分类无效'},400)
            with connection() as c:
                if not value:c.execute('DELETE FROM software_origins WHERE object_id=?',(obj['id'],))
                else:c.execute('INSERT INTO software_origins VALUES (?,?,?) ON CONFLICT(object_id) DO UPDATE SET value=excluded.value,updated=excluded.updated',(obj['id'],json.dumps(value),now()))
            return self.json_response({'ok':True})
        if route=='/api/tool-identity':
            value=body.get('value')
            if obj['kind'] not in ('agent','software') or value not in ('agent','software',None):return self.json_response({'error':'身份标记无效'},400)
            with connection() as c:
                if value is None:c.execute('DELETE FROM tool_identities WHERE object_id=?',(obj['id'],))
                else:c.execute('INSERT INTO tool_identities VALUES (?,?,?) ON CONFLICT(object_id) DO UPDATE SET value=excluded.value,updated=excluded.updated',(obj['id'],value,now()))
            return self.json_response({'ok':True})
        if route=='/api/category':
            value=body.get('value')
            if obj['kind']!='software' or (value is not None and (not isinstance(value,str) or value not in CATEGORIES)):return self.json_response({'error':'分类无效或对象不是软件'},400)
            with connection() as c:
                if value is None:c.execute('DELETE FROM categories WHERE object_id=?',(obj['id'],))
                else:c.execute('INSERT INTO categories VALUES (?,?,?) ON CONFLICT(object_id) DO UPDATE SET value=excluded.value,updated=excluded.updated',(obj['id'],value,now()))
            return self.json_response({'ok':True})
        if route=='/api/note':
            decision=body.get('decision','未标记');note=body.get('body','')
            if decision not in ['未标记','保留','待确认'] or not isinstance(note,str) or len(note)>2000:return self.json_response({'error':'备注格式无效或超过 2000 字'},400)
            with connection() as c:c.execute('INSERT INTO notes VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET decision=excluded.decision,body=excluded.body,updated=excluded.updated',(obj['id'],decision,note,now()))
            return self.json_response({'ok':True})
        if route=='/api/open':
            path=Path(obj.get('path',''))
            if not obj.get('path') or not path.exists():return self.json_response({'error':'路径已不存在，请重新检查'},409)
            directory=path if path.is_dir() else path.parent
            try: os.startfile(str(directory.resolve()))
            except OSError: return self.json_response({"error":"无法打开目录，请复制路径后手动打开"},500)
            return self.json_response({'ok':True})
        return self.json_response({'error':'Not found'},404)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765);args=parser.parse_args()
    initialize()
    if not latest():scan()
    print(f'Local Desk: http://127.0.0.1:{args.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
