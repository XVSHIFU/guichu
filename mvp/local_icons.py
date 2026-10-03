"""Extract local registered icon resources; never execute a registered command."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import uuid

EXTRACTION_LOCK=threading.Lock()

ROOT=Path(__file__).resolve().parent
CACHE=ROOT/'data'/'icons'

def icon_resource(value):
    value=os.path.expandvars(str(value)).strip()
    match=re.fullmatch(r'"?(.+?\.(?:exe|dll|ico))"?(?:\s*,\s*(-?\d+))?',value,re.I)
    if not match:return None
    path=Path(match[1])
    if not path.is_absolute() or str(path).startswith(('\\\\','//')) or not path.is_file():return None
    return path,int(match[2] or 0)

def enrich_icons(objects):
    CACHE.mkdir(parents=True,exist_ok=True)
    pending={};mapped=[]
    for obj in objects:
        if obj['kind']!='software':continue
        resource=icon_resource(obj.pop('_displayIcon',''))
        if not resource:continue
        path,index=resource
        try:stamp=path.stat().st_mtime_ns
        except OSError:continue
        key=hashlib.sha256(f'{str(path).casefold()}:{index}:{stamp}'.encode()).hexdigest()[:24]
        mapped.append((obj,key));obj['iconSource']='本机软件图标资源'
        if not (CACHE/(key+'.png')).is_file():pending[key]={'key':key,'path':str(path),'index':index}
    if pending and EXTRACTION_LOCK.acquire(blocking=False):
        def extract():
            manifest=CACHE/('pending-'+uuid.uuid4().hex+'.json')
            try:
                manifest.write_text(json.dumps(list(pending.values())),encoding='utf-8')
                result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(ROOT/'Extract-Icons.ps1'),'-Manifest',str(manifest),'-Destination',str(CACHE)],capture_output=True,timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                status={'returncode':result.returncode,'requested':len(pending),'available':sum((CACHE/(key+'.png')).is_file() for key in pending)}
            except (OSError,subprocess.TimeoutExpired) as exc:
                status={'error':type(exc).__name__,'requested':len(pending)}
            finally:
                try:
                    (CACHE/'last-result.json').write_text(json.dumps(status),encoding='utf-8')
                    manifest.unlink(missing_ok=True)
                finally:EXTRACTION_LOCK.release()
        threading.Thread(target=extract,daemon=True).start()
    for obj,key in mapped:
        if (CACHE/(key+'.png')).is_file():obj['iconUrl']='/local-icons/'+key+'.png'
        else:obj.pop('iconSource',None)
