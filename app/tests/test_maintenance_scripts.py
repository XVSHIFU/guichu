import json
from contextlib import closing, contextmanager
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import assistant_store
import action_store

FAKE_SERVER = '''import argparse,json,os,threading,sqlite3
from pathlib import Path
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import assistant_store,action_store
parser=argparse.ArgumentParser();parser.add_argument('--port',type=int);args=parser.parse_args()
root=Path(__file__).resolve().parent
@contextmanager
def connection():
 db=sqlite3.connect(root/'data/workbench.sqlite3')
 try:
  with db:yield db
 finally:db.close()
assistant_store.initialize(connection);action_store.initialize(connection)
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def respond(self,obj,status=200):
  self.send_response(status);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(obj).encode())
 def do_GET(self):
  if self.path=='/api/health': self.respond(dict(app='local-desk',pid=os.getpid(),server_path=str(Path(__file__).resolve()),busy=(root/'busy').exists(),busy_reasons=['fixture task']))
  elif self.path=='/api/fixture':
   with connection() as db:
    self.respond(dict(note=db.execute('SELECT body FROM notes').fetchone()[0],session=json.loads(db.execute('SELECT payload FROM assistant_sessions').fetchone()[0]),action=json.loads(db.execute('SELECT payload FROM actions').fetchone()[0])))
  else:self.respond(dict(token='fixture-token'))
 def do_POST(self):
  self.rfile.read(int(self.headers.get('Content-Length','0')))
  if (root/'busy').exists():return self.respond(dict(error='busy'),409)
  if self.headers.get('X-Desk-Token')!='fixture-token':return self.respond(dict(error='auth'),403)
  self.respond(dict(ok=True));threading.Thread(target=self.server.shutdown,daemon=True).start()
server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);server.serve_forever();server.server_close()
'''


@unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'), 'Windows maintenance scripts')
class MaintenanceScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='workbench-maintenance-')
        self.root = Path(self.temp.name)
        for name in ('Start', 'Stop', 'Backup', 'Restore'):
            shutil.copyfile(SCRIPTS / (name + '-Workbench.ps1'), self.root / (name + '-Workbench.ps1'))
        (self.root / 'server.py').write_text('import sys;sys.path.insert(0,' + repr(str(SCRIPTS)) + ')\n' + FAKE_SERVER, encoding='utf-8')
        (self.root / 'dist').mkdir()
        (self.root / 'dist/index.html').write_text('fixture')
        (self.root / 'data').mkdir()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.database = self.root / 'data/workbench.sqlite3'
        self.server_started = False
        with closing(sqlite3.connect(self.database)) as db, db:
            db.executescript('CREATE TABLE scans (id INTEGER PRIMARY KEY, at TEXT, payload TEXT); CREATE TABLE changes (id INTEGER PRIMARY KEY, at TEXT, object_id TEXT, name TEXT, kind TEXT, event TEXT); CREATE TABLE notes (id TEXT PRIMARY KEY, decision TEXT, body TEXT, updated TEXT); INSERT INTO notes VALUES ("one","待确认","before","fixture");')
            snapshot = dict(objects=[dict(id='one', kind='directory', name='Fixture')], relations=[], issues=[], disks=[], at='fixture', machine='test', scope='fixture only')
            db.execute('INSERT INTO scans (at,payload) VALUES (?,?)', ('fixture', json.dumps(snapshot)))
        assistant_store.initialize(self.connection)
        action_store.initialize(self.connection)
        assistant_store.dispatch(self.connection, '/api/assistant/create', {}, [])
        action_store.dispatch(self.connection, '/api/action/propose', {'object_id': 'one', 'decision': '保留', 'request_id': 'fixture'}, [{'id': 'one', 'name': 'Fixture'}])

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.database)
        try:
            with db:
                yield db
        finally:
            db.close()

    def tearDown(self):
        if self.server_started:
            (self.root / 'busy').unlink(missing_ok=True)
            record_path = self.root / 'data/server-process.json'
            if hasattr(self, 'valid_record'):
                record_path.write_text(json.dumps(self.valid_record), encoding='utf-8-sig')
            try:
                self.run_script('Stop', '-Port', str(self.port))
            except Exception:
                pass
        self.temp.cleanup()

    def run_script(self, name, *arguments):
        # Start-Process can inherit pipe handles in Windows PowerShell; real
        # files let us await the launcher independently of its hidden child.
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(self.root / (name + '-Workbench.ps1')), *arguments], stdout=stdout, stderr=stderr, timeout=30)
            stdout.seek(0)
            stderr.seek(0)
            result.stdout, result.stderr = stdout.read(), stderr.read()
            return result

    def assert_success(self, result):
        log = self.root / 'data/server-error.log'
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace') + (log.read_text(errors='replace') if log.exists() else ''))

    def test_backup_open_wal_database_and_restore_with_prebackup(self):
        active = sqlite3.connect(self.database)
        active.execute('PRAGMA journal_mode=WAL')
        active.execute('UPDATE notes SET body="snapshot"')
        active.commit()
        try:
            self.assert_success(self.run_script('Backup'))
        finally:
            active.close()
        backup = next((self.root / 'data/backups').glob('workbench-*.sqlite3'))
        with closing(sqlite3.connect(backup)) as db:
            self.assertEqual(db.execute('SELECT body FROM notes').fetchone()[0], 'snapshot')
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('UPDATE notes SET body="newer"')
            session = json.loads(db.execute('SELECT payload FROM assistant_sessions').fetchone()[0])
            session['title'] = 'changed-after-backup'
            db.execute('UPDATE assistant_sessions SET payload=?', (json.dumps(session),))
            action = json.loads(db.execute('SELECT payload FROM actions').fetchone()[0])
            action['state'] = 'conflict'
            db.execute('UPDATE actions SET payload=?', (json.dumps(action),))
        self.assert_success(self.run_script('Restore', '-BackupPath', str(backup), '-Port', str(self.port)))
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT body FROM notes').fetchone()[0], 'snapshot')
            self.assertEqual(json.loads(db.execute('SELECT payload FROM assistant_sessions').fetchone()[0])['title'], '新对话')
            self.assertEqual(json.loads(db.execute('SELECT payload FROM actions').fetchone()[0])['state'], 'pending')
        previous = next((self.root / 'data/backups').glob('before-restore-*.sqlite3'))
        with closing(sqlite3.connect(previous)) as db:
            self.assertEqual(db.execute('SELECT body FROM notes').fetchone()[0], 'newer')
        # Start the actual application from an isolated copy. A stored fixture
        # scan prevents startup from collecting this computer's environment.
        shutil.copytree(SCRIPTS / 'agent', self.root / 'agent', ignore=shutil.ignore_patterns('__pycache__'))
        for module in SCRIPTS.glob('*.py'):
            shutil.copyfile(module, self.root / module.name)
        result = self.run_script('Start', '-Port', str(self.port), '-NoBrowser')
        self.server_started = True
        self.assert_success(result)
        origin = f'http://127.0.0.1:{self.port}'
        with urllib.request.urlopen(origin + '/api/state') as response:
            restored = json.load(response)
        self.assertEqual(restored['data']['notes']['one']['body'], 'snapshot')
        self.assertEqual(restored['data']['at'], 'fixture')
        headers = {'Origin': origin, 'X-Desk-Token': restored['token'], 'Content-Type': 'application/json'}
        with urllib.request.urlopen(urllib.request.Request(origin + '/api/assistant/list', data=b'{}', headers=headers)) as response:
            sessions = json.load(response)['sessions']
        with urllib.request.urlopen(urllib.request.Request(origin + '/api/action/list', data=b'{}', headers=headers)) as response:
            actions = json.load(response)['actions']
        self.assertEqual(sessions[0]['title'], '新对话')
        self.assertEqual(actions[0]['state'], 'pending')

    def test_restore_rejects_outside_and_corrupt_backup_without_changing_database(self):
        original = self.database.read_bytes()
        outside = self.root / 'outside.sqlite3'
        outside.write_bytes(original)
        self.assertNotEqual(self.run_script('Restore', '-BackupPath', str(outside), '-Port', str(self.port)).returncode, 0)
        backups = self.root / 'data/backups'
        backups.mkdir()
        corrupt = backups / 'corrupt.sqlite3'
        corrupt.write_bytes(b'not sqlite')
        self.assertNotEqual(self.run_script('Restore', '-BackupPath', str(corrupt), '-Port', str(self.port)).returncode, 0)
        self.assertEqual(self.database.read_bytes(), original)

    def test_restore_refuses_database_with_active_writer(self):
        self.assert_success(self.run_script('Backup'))
        backup = next((self.root / 'data/backups').glob('workbench-*.sqlite3'))
        writer = sqlite3.connect(self.database)
        try:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('BEGIN IMMEDIATE')
            writer.execute('UPDATE notes SET body="active-writer"')
            result = self.run_script('Restore', '-BackupPath', str(backup), '-Port', str(self.port))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(writer.execute('SELECT body FROM notes').fetchone()[0], 'active-writer')
        finally:
            writer.rollback()
            writer.close()

    def test_port_collision_never_launches_or_stops_another_server(self):
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', self.port))
            occupied.listen()
            result = self.run_script('Start', '-Port', str(self.port), '-NoBrowser')
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((self.root / 'data/server-process.json').exists())
            self.assertEqual(occupied.getsockname()[1], self.port)

    def test_start_busy_refusal_identity_check_and_safe_stop(self):
        result = self.run_script('Start', '-Port', str(self.port), '-NoBrowser')
        self.server_started = True
        self.assert_success(result)
        record_path = self.root / 'data/server-process.json'
        self.valid_record = json.loads(record_path.read_text(encoding='utf-8-sig'))
        self.assert_success(self.run_script('Start', '-Port', str(self.port), '-NoBrowser'))
        (self.root / 'busy').write_text('busy')
        self.assertNotEqual(self.run_script('Stop', '-Port', str(self.port)).returncode, 0)
        (self.root / 'busy').unlink()
        tampered = dict(self.valid_record, start_ticks='0')
        record_path.write_text(json.dumps(tampered), encoding='utf-8-sig')
        self.assertNotEqual(self.run_script('Stop', '-Port', str(self.port)).returncode, 0)
        record_path.write_text(json.dumps(self.valid_record), encoding='utf-8-sig')
        self.assert_success(self.run_script('Backup'))
        backup = next((self.root / 'data/backups').glob('workbench-*.sqlite3'))
        self.assertNotEqual(self.run_script('Restore', '-BackupPath', str(backup), '-Port', str(self.port)).returncode, 0)
        self.assert_success(self.run_script('Stop', '-Port', str(self.port)))
        self.server_started = False


if __name__ == '__main__':
    unittest.main()
