import json, sqlite3, tempfile, unittest, zipfile, hashlib, sys
from contextlib import closing
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from workspace_transfer import export_workspace, import_workspace

class TransferTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.source=self.root/'source';(self.source/'data/config-backups').mkdir(parents=True)
  (self.source/'data/config-backups/original.toml').write_text('original bytes')
  (self.source/'data/model-provider.json').write_text(json.dumps({'providers':[{'encrypted_key':'SECRET'}]}))
  with closing(sqlite3.connect(self.source/'data/workbench.sqlite3')) as db,db:
   db.executescript('CREATE TABLE scans(id); CREATE TABLE notes(body); CREATE TABLE changes(id); INSERT INTO notes VALUES ("kept"); CREATE TABLE mcp_clients(id,payload); CREATE TABLE mcp_actions(payload);')
   db.execute('INSERT INTO mcp_clients VALUES (?,?)',('one',json.dumps({'credential':'TOKEN','enabled':True,'allowed_tools':['read']})))
   db.execute('INSERT INTO mcp_actions VALUES (?)',(json.dumps({'receipt':{'backup_path':str(self.source/'data/config-backups/original.toml')}}),))
  self.archive=self.root/'backup.zip'
 def tearDown(self):self.temp.cleanup()
 def test_roundtrip_keeps_original_and_rebases_backups(self):
  export_workspace(self.source,self.archive)
  target=self.root/'target';(target/'data').mkdir(parents=True);(target/'data/old.txt').write_text('previous')
  previous=import_workspace(target,self.archive)
  self.assertEqual((previous/'old.txt').read_text(),'previous')
  self.assertEqual((target/'data/config-backups/original.toml').read_text(),'original bytes')
  self.assertNotIn('SECRET',(target/'data/model-provider.json').read_text())
  with closing(sqlite3.connect(target/'data/workbench.sqlite3')) as db:
   self.assertEqual(db.execute('SELECT body FROM notes').fetchone()[0],'kept')
   record=json.loads(db.execute('SELECT payload FROM mcp_clients').fetchone()[0]);self.assertFalse(record['enabled']);self.assertEqual(record['credential'],'')
   receipt=json.loads(db.execute('SELECT payload FROM mcp_actions').fetchone()[0]);self.assertEqual(Path(receipt['receipt']['backup_path']).resolve(),(target/'data/config-backups/original.toml').resolve())
 def test_tampered_archive_does_not_touch_existing_data(self):
  export_workspace(self.source,self.archive)
  broken=self.root/'broken.zip'
  with zipfile.ZipFile(self.archive) as src,zipfile.ZipFile(broken,'w') as dst:
   for name in src.namelist():dst.writestr(name,b'bad' if name=='workbench.sqlite3' else src.read(name))
  target=self.root/'target';(target/'data').mkdir(parents=True);(target/'data/kept').write_text('safe')
  with self.assertRaisesRegex(ValueError,'Checksum'):import_workspace(target,broken)
  self.assertEqual((target/'data/kept').read_text(),'safe')
 def test_traversal_and_duplicate_entries_rejected(self):
  for name in ['../escape','config-backups/../../escape','config-backups/x:stream']:
   archive=self.root/'bad.zip';content=b'x'
   with zipfile.ZipFile(archive,'w') as out:
    out.writestr(name,content);out.writestr('manifest.json',json.dumps({'format':'guichu-workspace','version':1,'files':{name:hashlib.sha256(content).hexdigest()}}))
   with self.assertRaises(ValueError):import_workspace(self.source,archive)
 def test_destination_not_overwritten(self):
  export_workspace(self.source,self.archive)
  with self.assertRaises(ValueError):export_workspace(self.source,self.archive)

if __name__=='__main__':unittest.main()
