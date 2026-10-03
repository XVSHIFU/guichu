from contextlib import contextmanager
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import category_action_store as categories
import claude_action_store as claude
import claude_config_action as adapter
import mcp_config_action as files

class ExtendedActionsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        @contextmanager
        def connection():
            db=sqlite3.connect(self.root/'test.db')
            try:
                with db:yield db
            finally:db.close()
        self.connection=connection
        categories.initialize(self.connection);claude.initialize(self.connection)
        self.objects=[{'id':'a','kind':'software','name':'Alpha'},{'id':'b','kind':'software','name':'Beta'}]
        self.path=self.root/'.claude.json'
        self.original=b'{"mcpServers":{"sample":{"command":"fixture","env":{"TOKEN":"secret-only-in-backup"}},"other":{"url":"https://invalid.example"}},"preferences":{"a":2}}'
        self.path.write_bytes(self.original)
        self.mcp_object={'id':'c','name':'sample','kind':'mcp','scope':'claude','source':'用户配置','path':str(self.path)}

    def tearDown(self):self.temp.cleanup()
    def category(self,op,body):return categories.dispatch(self.connection,op,body,self.objects)
    def mcp(self,op,body):return claude.dispatch(self.connection,'/api/mcp-action/'+op,body,[self.mcp_object],self.path,self.root/'backups')

    def test_batch_atomic_apply_restore_idempotence(self):
        body={'request_id':'one','changes':[{'object_id':'a','category':'开发工具'},{'object_id':'b','category':'办公与协作'}]}
        result,status=self.category('propose',body);self.assertEqual(status,200)
        action=result['action'];key={'id':action['id'],'revision':1}
        self.assertEqual(self.category('propose',body)[0]['action']['id'],action['id'])
        with self.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM categories').fetchone()[0],0)
        result,status=self.category('confirm',key);self.assertEqual(status,200)
        self.assertEqual(self.category('confirm',key)[0]['action'],result['action'])
        self.assertEqual(self.category('restore',key)[1],200)
        with self.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM categories').fetchone()[0],0)

    def test_batch_conflict_never_partially_writes(self):
        action=self.category('propose',{'request_id':'one','changes':[{'object_id':'a','category':'开发工具'},{'object_id':'b','category':'办公与协作'}]})[0]['action']
        with self.connection() as db:db.execute('INSERT INTO categories VALUES(?,?,?)',('b','其他软件','external'))
        self.assertEqual(self.category('confirm',{'id':action['id'],'revision':1})[1],409)
        with self.connection() as db:self.assertIsNone(db.execute("SELECT value FROM categories WHERE object_id='a'").fetchone())

    def test_batch_restore_conflict_preserves_external_change(self):
        action=self.category('propose',{'request_id':'one','changes':[{'object_id':'a','category':'开发工具'}]})[0]['action']
        key={'id':action['id'],'revision':1}
        self.assertEqual(self.category('confirm',key)[1],200)
        with self.connection() as db:db.execute("UPDATE categories SET value='其他软件',updated='external' WHERE object_id='a'")
        self.assertEqual(self.category('restore',key)[1],409)
        with self.connection() as db:self.assertEqual(db.execute("SELECT value FROM categories WHERE object_id='a'").fetchone()[0],'其他软件')

    def test_claude_remove_backup_restore_redacted(self):
        result,status=self.mcp('propose',{'object_id':'c','enabled':False,'request_id':'one'})
        self.assertEqual(status,200);action=result['action'];key={'id':action['id'],'revision':1}
        self.assertNotIn('secret-only-in-backup',json.dumps(action));self.assertEqual(self.path.read_bytes(),self.original)
        applied,status=self.mcp('confirm',key);self.assertEqual(status,200)
        backup=Path(applied['action']['receipt']['backup_path'])
        self.assertEqual(backup.read_bytes(),self.original)
        if os.name=='nt':self.assertEqual(files._dacl(backup).replace('D:PAI','D:P',1),files._private_dacl())
        current=json.loads(self.path.read_text());self.assertNotIn('sample',current['mcpServers']);self.assertEqual(current['preferences'],{'a':2})
        self.assertEqual(self.mcp('confirm',key)[1],200)
        self.assertEqual(len(list((self.root/'backups').glob('*.bak'))),1)
        self.assertEqual(self.mcp('restore',key)[1],200);self.assertEqual(self.path.read_bytes(),self.original)

    def test_claude_restore_never_overwrites_subsequent_changes(self):
        action=self.mcp('propose',{'object_id':'c','enabled':False,'request_id':'one'})[0]['action']
        key={'id':action['id'],'revision':1}
        self.assertEqual(self.mcp('confirm',key)[1],200)
        newer=self.path.read_bytes()+b'\n';self.path.write_bytes(newer)
        self.assertEqual(self.mcp('restore',key)[1],409)
        self.assertEqual(self.path.read_bytes(),newer)

    def test_claude_conflict_duplicate_json_and_enable_rejected(self):
        self.assertEqual(self.mcp('propose',{'object_id':'c','enabled':True,'request_id':'enable'})[1],400)
        action=self.mcp('propose',{'object_id':'c','enabled':False,'request_id':'one'})[0]['action']
        self.path.write_bytes(self.original+b' ')
        self.assertEqual(self.mcp('confirm',{'id':action['id'],'revision':1})[1],409)
        self.path.write_text('{"mcpServers":{"sample":{}},"mcpServers":{"sample":{}}}')
        with self.assertRaises(ValueError):adapter.preview(self.path,'sample',False)

if __name__=='__main__':unittest.main()
