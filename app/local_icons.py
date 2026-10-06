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

def appx_resources(obj):
    import xml.etree.ElementTree as ET
    root=Path(obj.get('path',''))
    try:
        manifest=root/'AppxManifest.xml'
        if manifest.stat().st_size>2*1024*1024:return []
        tree=ET.fromstring(manifest.read_bytes())
        names=[]
        for node in tree.iter():
            for key in ('Square44x44Logo','Square150x150Logo','Logo'):
                if node.get(key):names.append(node.get(key))
            if node.tag.split('}')[-1]=='Logo' and node.text:names.append(node.text)
        result=[]
        for name in dict.fromkeys(names):
            relative=Path(name)
            if relative.is_absolute() or '..' in relative.parts or ':' in name:continue
            base=root/relative
            candidates=[base]
            # Windows resource qualifiers may replace the unqualified filename.
            candidates.extend(sorted(base.parent.glob(base.stem+'.*'+base.suffix),key=lambda p:('targetsize-64' not in p.name,'scale-200' not in p.name,p.name))[:30])
            for path in candidates:
                if path.suffix.lower() in ('.png','.jpg','.jpeg','.ico') and path.is_file() and path.stat().st_size<=8*1024*1024:
                    result.append((path,0,'应用包图标'))
        return result
    except (OSError,ValueError,ET.ParseError):return []


def shortcut_resources():
    roots=[Path(os.environ[k])/'Microsoft/Windows/Start Menu/Programs' for k in ('APPDATA','PROGRAMDATA') if os.environ.get(k)]
    roots += [Path.home()/'Desktop']
    result={}
    for root in roots:
        pending=[(root,0)];count=0
        while pending and count<2500:
            folder,depth=pending.pop()
            try:
                if folder.is_symlink() or folder.is_junction():continue
                with os.scandir(folder) as entries:
                    for entry in entries:
                        count+=1
                        if count>2500:break
                        if entry.is_dir(follow_symlinks=False) and depth<5:pending.append((Path(entry.path),depth+1))
                        elif entry.is_file(follow_symlinks=False) and entry.name.lower().endswith('.lnk'):
                            result.setdefault(Path(entry.name).stem.casefold(),[]).append(Path(entry.path))
            except OSError:continue
    return result


def enrich_icons(objects):
    CACHE.mkdir(parents=True,exist_ok=True)
    shortcuts=shortcut_resources()
    pending={};mapped=[]
    for obj in objects:
        if obj['kind'] not in ('software','agent'):continue
        candidates=[]
        if obj.get('packageFamily'):candidates.extend(appx_resources(obj))
        for value,label in [(obj.get('_displayIcon',''),'注册表图标'),(obj.get('executable',''),'程序图标'),(obj.get('path','') if obj.get('portable') else '', '程序图标')]:
            resource=icon_resource(value)
            if resource:candidates.append((*resource,label))
        candidates.extend((path,0,'快捷方式图标') for path in shortcuts.get(obj['name'].casefold(),[])[:4])
        choices=[]
        for path,index,label in candidates[:16]:
            try:stamp=path.stat().st_mtime_ns
            except OSError:continue
            key=hashlib.sha256(f'v2:{str(path).casefold()}:{index}:{stamp}'.encode()).hexdigest()[:24]
            choices.append((key,label))
            if not (CACHE/(key+'.png')).is_file():pending[key]={'key':key,'path':str(path),'index':index}
        mapped.append((obj,choices))
    if pending:
        with EXTRACTION_LOCK:
            manifest=CACHE/('pending-'+uuid.uuid4().hex+'.json')
            status={}
            try:
                manifest.write_text(json.dumps(list(pending.values())),encoding='utf-8')
                shell=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
                result=subprocess.run([str(shell),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(ROOT/'Extract-Icons.ps1'),'-Manifest',str(manifest),'-Destination',str(CACHE)],capture_output=True,timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                status={'returncode':result.returncode,'requested':len(pending),'available':sum((CACHE/(key+'.png')).is_file() for key in pending)}
            except (OSError,subprocess.TimeoutExpired) as exc:
                status={'error':type(exc).__name__,'requested':len(pending)}
            finally:
                (CACHE/'last-result.json').write_text(json.dumps(status),encoding='utf-8')
                manifest.unlink(missing_ok=True)
    for obj,choices in mapped:
        for key,label in choices:
            if (CACHE/(key+'.png')).is_file():
                obj['iconUrl']='/local-icons/'+key+'.png';obj['iconSource']=label
                break
