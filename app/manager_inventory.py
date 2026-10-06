"""Bounded local package-manager receipts. No manager commands or scripts run."""
import hashlib
import json
import os
from pathlib import Path
import re
import tomllib
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit
from email.parser import Parser
from datetime import datetime, timezone
from package_inventory import local, read


def download_kind(value):
    if not isinstance(value,str):return '未知'
    try:
        url=urlsplit(value)
        if url.scheme=='file':return '本地 / 离线文件'
        if url.scheme not in ('http','https') or not url.hostname:return '未知'
        if url.hostname.lower()=='github.com' and '/releases/download/' in url.path:return 'GitHub Releases'
        if url.hostname.lower() in ('registry.npmjs.org','registry.yarnpkg.com','pypi.org','files.pythonhosted.org','repo.anaconda.com','conda.anaconda.org'):return '包仓库'
        return '其他网站'
    except ValueError:return '未知'


def tool_version(folder,name):
    canonical=lambda s:re.sub('[-_.]+','-',s).lower()
    try:
        for info in children(folder/'Lib/site-packages'):
            if not info.name.endswith('.dist-info'):continue
            metadata=Parser().parsestr(read(info/'METADATA'),headersonly=True)
            if canonical(metadata.get('Name',''))==canonical(name):return metadata.get('Version','')
    except (OSError,ValueError,UnicodeError):pass
    return ''


def children(path):
    try:
        path=local(path)
        with os.scandir(path) as rows:
            result=[]
            for i,row in enumerate(rows):
                if i>=1000:raise ValueError('安装记录超过1000项')
                if row.is_dir(follow_symlinks=False):result.append(Path(row.path))
            return result
    except FileNotFoundError:return []


def resolved_under(path, root):
    target=path.resolve(strict=True);boundary=root.resolve(strict=True)
    if not target.is_relative_to(boundary):raise ValueError('安装链接超出管理目录')
    return local(target)


def npm_prefixes():
    result=[]
    configured=os.environ.get('NPM_CONFIG_PREFIX') or os.environ.get('npm_config_prefix')
    if configured:result.append(Path(configured))
    try:
        for line in read(Path.home()/'.npmrc').splitlines():
            if re.match(r'^\s*prefix\s*=',line,re.I):
                value=line.split('=',1)[1].strip().strip('"\'')
                value=re.sub(r'\$\{([^}]+)\}',lambda m:os.environ.get(m[1],''),value)
                result.append(Path(os.path.expandvars(value)).expanduser())
    except (OSError,ValueError,UnicodeError):pass
    if os.environ.get('APPDATA'):result.append(Path(os.environ['APPDATA'])/'npm')
    return [p for p in result if p.is_absolute()]


def manager_roots():
    home=Path.home();roaming=Path(os.environ.get('APPDATA',home/'AppData/Roaming'));localapp=Path(os.environ.get('LOCALAPPDATA',home/'AppData/Local'))
    roots=[('Scoop',Path(os.environ.get('SCOOP',home/'scoop'))/'apps'),
           ('Scoop',Path(os.environ.get('SCOOP_GLOBAL',Path(os.environ.get('PROGRAMDATA',r'C:\ProgramData'))/'scoop'))/'apps'),
           ('Chocolatey',Path(os.environ.get('ChocolateyInstall',Path(os.environ.get('PROGRAMDATA',r'C:\ProgramData'))/'chocolatey'))/'lib'),
           ('pipx',Path(os.environ.get('PIPX_HOME',home/'pipx'))/'venvs'),('pipx',home/'.local/share/pipx/venvs'),
           ('uv',Path(os.environ.get('UV_TOOL_DIR',roaming/'uv/tools'))),
           ('Yarn',Path(os.environ.get('YARN_GLOBAL_FOLDER',localapp/'Yarn/Data/global')))]
    pnpm=Path(os.environ.get('PNPM_HOME',localapp/'pnpm'))/'global'
    for version in children(pnpm):
        if (version/'package.json').is_file():roots.append(('pnpm',version))
        else:roots.extend(('pnpm',p) for p in children(version) if (p/'package.json').is_file())
    return roots


def collect_managers(locations=None):
    result={'objects':[],'relations':[],'issues':[],'sources':[]};at=datetime.now(timezone.utc).isoformat()
    discovery={'id':'manager-discovery','status':'success','checkedAt':at};result['sources'].append(discovery)
    if locations is None:
        try:locations=manager_roots()
        except (OSError,ValueError):
            locations=[];discovery['status']='failed'
            result['issues'].append({'sourceKey':'manager-discovery','name':'包管理器位置','reason':'部分管理器目录不可读'})
    seen=set()
    for channel,root in locations:
        boundary=next((p.parent for p in root.parents if p.name=='global'),root) if channel=='pnpm' else root
        if channel=='pnpm':
            try:root=resolved_under(root,boundary)
            except (OSError,ValueError):pass
        key='manager:'+hashlib.sha256((channel+str(root).casefold()).encode()).hexdigest()[:16]
        if key in seen:continue
        seen.add(key);state={'id':key,'status':'success','checkedAt':at};result['sources'].append(state)
        def add(name,version,path,receipt,commands=(),form='',download='未知'):
            if not isinstance(name,str) or not name or len(name)>200:raise ValueError('包名称无效')
            oid='software:'+hashlib.sha256((key+name.casefold()).encode()).hexdigest()[:16]
            result['objects'].append({'id':oid,'kind':'software','name':name,'packageName':name,'version':str(version)[:120],
                'path':str(path),'installPath':str(path),'managedChannel':channel,'managerReceipt':str(receipt),'managedDownload':download,
                'source':channel+' 安装记录','sourceKey':key,'checkedAt':at,'status':'已登记','managerRecord':True,
                'sourceDependencies':['manager-discovery'],
                'installationForm':form,'commands':list(commands)[:30],
                'description':channel+' 管理的本地安装；依据安装记录识别。'})
        def failure():
            state['status']='partial'
            if not any(i.get('sourceKey')==key for i in result['issues']):result['issues'].append({'sourceKey':key,'name':channel+' 安装记录','reason':'部分安装记录不可读或不完整'})
        try:
            root=local(root)
            if channel in ('pnpm','Yarn'):
                if not root.exists():continue
                # Parent lockfile alone may describe an uninstalled project.
                marker=root/'node_modules'/('.modules.yaml' if channel=='pnpm' else '.yarn-integrity')
                read(resolved_under(marker,boundary) if channel=='pnpm' else marker)
                dependencies=json.loads(read(root/'package.json')).get('dependencies',{})
                if not isinstance(dependencies,dict) or len(dependencies)>1000:raise ValueError('invalid dependencies')
                for name in dependencies:
                    try:
                        if not re.fullmatch(r'(?:@[\w.-]+/)?[\w.-]+',name):raise ValueError('invalid package name')
                        package=resolved_under(root/'node_modules'/name,boundary if channel=='pnpm' else root)
                        metadata=json.loads(read(package/'package.json'))
                        if metadata.get('name')!=name:raise ValueError('name mismatch')
                        bins=metadata.get('bin',{});commands=list(bins) if isinstance(bins,dict) else [name.rsplit('/',1)[-1]] if isinstance(bins,str) else []
                        add(name,metadata.get('version',''),package,marker,commands,'命令行')
                    except (OSError,ValueError,TypeError,AttributeError):failure()
                continue
            for package in children(root):
                try:
                    if channel=='Scoop':
                        current=package/'current'
                        if not current.exists():continue
                        folder=resolved_under(current,package)
                        receipt=next((folder/n for n in ('scoop-install.json','install.json') if (folder/n).is_file()),None)
                        manifest=next((folder/n for n in ('scoop-manifest.json','manifest.json') if (folder/n).is_file()),None)
                        if not receipt or not manifest:
                            if package.name=='scoop' and (folder/'.git').exists():continue
                            raise ValueError('missing scoop receipt')
                        install=json.loads(read(receipt));meta=json.loads(read(manifest))
                        if not isinstance(install,dict) or not isinstance(meta,dict):raise ValueError('invalid scoop metadata')
                        url=meta.get('architecture',{}).get(install.get('architecture',''),{}).get('url',meta.get('url'))
                        urls=url if isinstance(url,list) else [url]
                        kinds={download_kind(value) for value in urls}
                        add(package.name,meta.get('version',''),folder,receipt,download=kinds.pop() if len(kinds)==1 else '未知')
                    elif channel=='Chocolatey':
                        specs=list(package.glob('*.nuspec'))[:2]
                        if len(specs)!=1 or not any(package.glob('*.nupkg')):continue
                        meta=ET.fromstring(read(specs[0]));values={n.tag.split('}')[-1]:n.text for n in meta.iter() if n.tag.split('}')[-1] in ('id','version')}
                        add(values.get('id'),values.get('version',''),package,specs[0])
                    elif channel=='pipx':
                        receipt=package/'pipx_metadata.json'
                        if not receipt.exists():continue
                        meta=json.loads(read(receipt)).get('main_package',{})
                        if not (package/'pyvenv.cfg').is_file():raise ValueError('missing environment')
                        add(meta.get('package'),meta.get('package_version',''),package,receipt,form='命令行')
                    elif channel=='uv':
                        receipt=package/'uv-receipt.toml'
                        if not receipt.exists():continue
                        meta=tomllib.loads(read(receipt))
                        if not (package/'pyvenv.cfg').is_file() or not isinstance(meta.get('tool'),dict):raise ValueError('invalid tool environment')
                        add(package.name,tool_version(package,package.name),package,receipt,form='命令行')
                except (OSError,ValueError,TypeError,AttributeError,ET.ParseError,UnicodeError):failure()
        except (OSError,ValueError,TypeError,AttributeError,UnicodeError):failure()
    return result
