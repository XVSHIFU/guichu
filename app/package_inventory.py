"""Bounded npm/pip metadata discovery. Never imports packages or runs commands."""
import configparser
from datetime import datetime, timezone
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

MAX_ENTRIES = 1500
MAX_BYTES = 512 * 1024


def local(path):
    path = Path(path)
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise ValueError('不是本机绝对路径')
    if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in (path, *path.parents)):
        raise ValueError('链接路径未检查')
    return path


def read(path):
    path = local(path)
    meta = path.stat()
    if not stat.S_ISREG(meta.st_mode) or meta.st_size > MAX_BYTES:
        raise ValueError('元数据超过大小限制或不是普通文件')
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES: raise ValueError('元数据超过大小限制')
    return raw.decode('utf-8-sig')


def roots(registrations=()):
    candidates = []
    from manager_inventory import npm_prefixes
    candidates.extend(('npm',p/'node_modules') for p in npm_prefixes())
    if os.environ.get('APPDATA'):
        candidates.append(('npm', Path(os.environ['APPDATA']) / 'npm' / 'node_modules'))
    candidates.append(('pip', Path(sys.prefix) / 'Lib' / 'site-packages'))
    # myEnv reference: enumerate registered environments without starting Python.
    try:
        for value in read(Path.home()/'.conda/environments.txt').splitlines()[:200]:
            environment=Path(value.strip())
            if environment.is_absolute() and (environment/'conda-meta').is_dir():
                candidates.append(('pip',environment/'Lib/site-packages'))
    except (OSError,ValueError,UnicodeError):pass
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
            for view in (winreg.KEY_WOW64_64KEY,winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive,r'Software\Python',0,winreg.KEY_READ|view) as parent:
                        for i in range(min(winreg.QueryInfoKey(parent)[0],128)):
                            company=winreg.EnumKey(parent,i)
                            with winreg.OpenKey(parent,company) as vendor:
                                for j in range(min(winreg.QueryInfoKey(vendor)[0],128)):
                                    try:
                                        with winreg.OpenKey(vendor,winreg.EnumKey(vendor,j)+r'\InstallPath') as entry:
                                            value=winreg.QueryValueEx(entry,'')[0]
                                            if isinstance(value,str) and Path(value).is_absolute():candidates.append(('pip',Path(value)/'Lib/site-packages'))
                                    except OSError:continue
                except OSError:continue
    except ImportError:pass
    for raw in os.environ.get('PATH', '').split(os.pathsep):
        if not raw: continue
        p = Path(raw.strip('"'))
        if not p.is_absolute(): continue
        candidates.append(('npm', p / 'node_modules'))
        candidates.append(('pip', (p.parent if p.name.lower() in ('scripts', 'bin') else p) / 'Lib' / 'site-packages'))
    for source in registrations:
        if source.get('type') in ('npm', 'pip'):
            candidates.append((source['type'], Path(source['path'])))
    seen = set()
    for manager, path in candidates:
        key = (manager, os.path.normcase(str(path)))
        if key not in seen:
            seen.add(key)
            yield manager, path


def collect_packages(registrations=(), locations=None):
    result = {'objects': [], 'relations': [], 'sources': [], 'issues': []}
    at = datetime.now(timezone.utc).isoformat()
    for manager, root in (locations if locations is not None else roots(registrations)):
        key = 'packages:' + hashlib.sha256((manager + ':' + os.path.normcase(str(root))).encode()).hexdigest()[:16]
        state = {'id': key, 'status': 'success', 'checkedAt': at}
        result['sources'].append(state)
        uncertain_enumeration = False
        def object_id(path):
            return 'software:' + hashlib.sha256((key + ':' + os.path.normcase(str(path))).encode()).hexdigest()[:16]
        def issue(message, failed_path=None):
            nonlocal uncertain_enumeration
            state['status'] = 'partial'
            if failed_path is None:
                uncertain_enumeration = True
                state.pop('retainObjectIds', None)
            elif not uncertain_enumeration:
                state.setdefault('retainObjectIds', []).append(object_id(failed_path))
            row = {'sourceKey': key, 'name': manager + ' 安装元数据', 'reason': message}
            if row not in result['issues']: result['issues'].append(row)
        try:
            root = local(root)
            pending = [root]
            count = 0
            while pending:
                directory = local(pending.pop())
                try:
                    entries = os.scandir(directory)
                except FileNotFoundError:
                    continue
                with entries:
                    for entry in entries:
                        count += 1
                        if count > MAX_ENTRIES:
                            issue('超过1500项枚举上限，结果不完整')
                            pending.clear()
                            break
                        try:
                            folder = local(entry.path)
                            if not entry.is_dir(follow_symlinks=False): continue
                            if manager == 'npm' and entry.name.startswith('@') and directory == root:
                                pending.append(folder)
                                continue
                            if manager == 'pip' and not entry.name.endswith('.dist-info'): continue
                            if manager == 'npm':
                                metadata = json.loads(read(folder / 'package.json'))
                                if not isinstance(metadata, dict): raise ValueError('包元数据类型无效')
                                name, version = metadata.get('name'), metadata.get('version', '')
                                bins = metadata.get('bin', {})
                                if isinstance(bins, str) and isinstance(name, str): bins = {name.rsplit('/', 1)[-1]: bins}
                                if not isinstance(bins, dict): raise ValueError('命令入口元数据无效')
                                commands = [k for k, v in bins.items() if isinstance(k, str) and isinstance(v, str)]
                            else:
                                metadata = Parser().parsestr(read(folder / 'METADATA'), headersonly=True)
                                name, version = metadata.get('Name'), metadata.get('Version', '')
                                config = configparser.ConfigParser(interpolation=None)
                                try: config.read_string(read(folder / 'entry_points.txt'))
                                except FileNotFoundError: continue
                                commands = [k for group in ('console_scripts', 'gui_scripts') if config.has_section(group) for k in config[group]]
                            if not commands: continue
                            if not isinstance(name, str) or not name or len(name) > 200: raise ValueError('包名称无效')
                            commands = [c[:200] for c in commands[:30]]
                            installer = ''
                            if manager == 'pip':
                                try: installer = read(folder / 'INSTALLER').strip().lower()
                                except (OSError, ValueError, UnicodeError): pass
                            managed = ''
                            basis = ''
                            download = '未知'
                            if manager == 'pip':
                                try:
                                    from manager_inventory import download_kind
                                    download=download_kind(json.loads(read(folder/'direct_url.json')).get('url'))
                                except (OSError,ValueError,TypeError,UnicodeError):pass
                            if manager == 'npm':
                                from manager_inventory import npm_prefixes
                                if any(os.path.normcase(str(root.parent))==os.path.normcase(str(p)) for p in npm_prefixes()):
                                    managed='npm';basis='npm 配置的全局前缀与已安装包；表示当前管理位置，不还原历史安装命令'
                                try:
                                    lock=json.loads(read(root/'.package-lock.json'))
                                    entry=lock.get('packages',{}).get('node_modules/'+name,{})
                                    if entry.get('version')==version:
                                        managed='npm';basis='npm 隐藏锁文件与已安装包版本一致'
                                except (OSError,ValueError,TypeError,UnicodeError):pass
                            oid = object_id(folder)
                            result['objects'].append({'id': oid, 'kind': 'software', 'name': name, 'packageName': name,
                                'version': str(version)[:120], 'source': 'npm 安装元数据' if manager == 'npm' else 'Python 包元数据', 'sourceKey': key,
                                'checkedAt': at, 'path': str(folder), 'installPath': str(root), 'scope': manager,
                                'distribution': manager, 'packageInstaller': installer, 'managedChannel': managed, 'managerBasis': basis, 'managedDownload': download, 'commands': commands, 'status': '已声明命令入口',
                                'description': '安装包声明的命令：' + '、'.join(commands) + '。未执行或验证入口可运行；包可提供终端或本地网页界面。'})
                        except FileNotFoundError:
                            # Non-packages are common in node_modules; incomplete dist-info is not.
                            if manager == 'pip': issue('部分安装元数据缺失，结果不完整', entry.path)
                        except (OSError, ValueError, configparser.Error, UnicodeError, TypeError):
                            issue('部分包元数据不可读取或无效，结果不完整', None if entry.name.startswith('@') else entry.path)
        except (OSError, ValueError):
            issue('安装目录不可读取或为链接，结果不完整')
    return result
