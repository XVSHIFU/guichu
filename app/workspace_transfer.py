"""Offline workspace transfer. Use Transfer-Workbench.ps1 to enforce the maintenance lock."""
from contextlib import closing
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath

def private_file(path):
    if os.name == 'nt':
        from mcp_config_action import _private_dacl, _set_dacl
        _set_dacl(path, _private_dacl())
    else: path.chmod(0o600)

MAX_BYTES = 2 * 1024**3
ALLOWED = {'workbench.sqlite3', 'model-provider.json', 'icons', 'config-backups'}

def unlinked(path):
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part,'is_junction') and part.is_junction()):
            raise ValueError('Linked paths are not supported: '+str(path))

def verify_db(path):
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    try:
        if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:
            raise ValueError('Database integrity check failed')
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'scans','notes','changes'}.issubset(tables):
            raise ValueError('Not a Guichu database')
    finally: db.close()

def scrub_credentials(data):
    settings=data/'model-provider.json'
    if settings.exists():
        content=json.loads(settings.read_text(encoding='utf-8-sig'))
        def scrub(value):
            if isinstance(value,dict):
                return {k:('' if k=='encrypted_key' else scrub(v)) for k,v in value.items()}
            if isinstance(value,list): return [scrub(v) for v in value]
            return value
        settings.write_text(json.dumps(scrub(content),ensure_ascii=False),encoding='utf-8')
    with closing(sqlite3.connect(data/'workbench.sqlite3')) as db, db:
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'mcp_clients' in tables:
            for ident,raw in db.execute('SELECT id,payload FROM mcp_clients').fetchall():
                record=json.loads(raw);record.update(credential='',enabled=False,allowed_tools=[])
                db.execute('UPDATE mcp_clients SET payload=? WHERE id=?',(json.dumps(record),ident))

def export_workspace(root, destination):
    root=root.resolve();data=root/'data';unlinked(data);unlinked(destination)
    if destination.exists(): raise ValueError('Destination already exists')
    verify_db(data/'workbench.sqlite3')
    destination.parent.mkdir(parents=True,exist_ok=True)
    temp=destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with tempfile.TemporaryDirectory(prefix='guichu-export-') as staging:
            staged=Path(staging)
            for name in ALLOWED:
                source=data/name
                if not source.exists():continue
                unlinked(source)
                if source.is_dir():
                    for child in source.rglob('*'):unlinked(child)
                    shutil.copytree(source,staged/name)
                elif name=='workbench.sqlite3':
                    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(staged/name)) as dst:src.backup(dst)
                else:shutil.copy2(source,staged/name)
            scrub_credentials(staged)
            files={p.relative_to(staged).as_posix():p for p in staged.rglob('*') if p.is_file()}
            if sum(p.stat().st_size for p in files.values())>MAX_BYTES:raise ValueError('Archive exceeds 2 GiB limit')
            manifest={'format':'guichu-workspace','version':1,'source_data':str(data),'credentials':'removed','files':{name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in files.items()}}
            with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as archive:
                for name,p in files.items():archive.write(p,name)
                archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
        private_file(temp)
        os.replace(temp,destination)
    finally:
        if temp.exists():temp.unlink()
    return destination

def import_workspace(root, source):
    root=root.resolve();data=root/'data';unlinked(root);unlinked(data);unlinked(source)
    staged=root/('data-import-'+uuid.uuid4().hex);staged.mkdir()
    previous=root/('data-before-import-'+uuid.uuid4().hex)
    try:
        with zipfile.ZipFile(source) as archive:
            infos=archive.infolist();names=[i.filename for i in infos]
            if len(names)>50000 or len({n.casefold() for n in names})!=len(names):raise ValueError('Duplicate or excessive entries')
            if sum(i.file_size for i in infos)>MAX_BYTES:raise ValueError('Archive exceeds 2 GiB limit')
            manifest=json.loads(archive.read('manifest.json'))
            if manifest.get('format')!='guichu-workspace' or manifest.get('version')!=1:raise ValueError('Unsupported archive')
            expected=manifest['files']
            if set(names)!=set(expected)|{'manifest.json'}:raise ValueError('Archive manifest mismatch')
            for name,digest in expected.items():
                parts=PurePosixPath(name).parts
                if not parts or parts[0] not in ALLOWED or '\\' in name or ':' in name or any(p in {'.','..'} or p.endswith((' ','.')) for p in parts) or name.startswith('/'):
                    raise ValueError('Invalid archive path')
                content=archive.read(name)
                if hashlib.sha256(content).hexdigest()!=digest:raise ValueError('Checksum mismatch')
                target=staged.joinpath(*parts);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content);private_file(target)
        verify_db(staged/'workbench.sqlite3');scrub_credentials(staged)
        # Only rebase known backup references. Managed software paths remain unchanged.
        old=manifest.get('source_data','')
        if old:
            with closing(sqlite3.connect(staged/'workbench.sqlite3')) as db, db:
                tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table in ('mcp_actions','claude_actions'):
                    if table not in tables:continue
                    for rowid,raw in db.execute(f'SELECT rowid,payload FROM {table}').fetchall():
                        record=json.loads(raw)
                        def rebase(value,key=''):
                            if isinstance(value,dict):return {k:rebase(v,k) for k,v in value.items()}
                            if isinstance(value,list):return [rebase(v,key) for v in value]
                            if key in {'backup_path','backup_location'} and isinstance(value,str):
                                try:
                                    rel=Path(value).resolve().relative_to((Path(old)/'config-backups').resolve())
                                    return str(data/'config-backups'/rel)
                                except ValueError:pass
                            return value
                        db.execute(f'UPDATE {table} SET payload=? WHERE rowid=?',(json.dumps(rebase(record)),rowid))
        if data.exists():os.replace(data,previous)
        try:os.replace(staged,data)
        except BaseException:
            if previous.exists():os.replace(previous,data)
            raise
        return previous if previous.exists() else None
    finally:
        if staged.exists():shutil.rmtree(staged)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['export','import']);parser.add_argument('path',type=Path);args=parser.parse_args()
    root=Path(__file__).resolve().parent
    try:
        if args.action=='export':print('Exported:',export_workspace(root,args.path.absolute()))
        else:print('Imported. Previous data preserved at:',import_workspace(root,args.path.absolute()));print('Reconfigure model credentials and review MCP connections before use.')
    except (ValueError,OSError,sqlite3.Error,zipfile.BadZipFile,KeyError) as exc:raise SystemExit(str(exc))
