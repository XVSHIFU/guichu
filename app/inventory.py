"""Read-only local inventory collection, separate from HTTP and persistence."""
import os,shutil,tomllib,json,hashlib
from pathlib import Path
from datetime import datetime,timezone
import psutil,yaml
from local_icons import enrich_icons
HOME=Path.home()
def now():return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
def identity(kind,value):return kind+':'+hashlib.sha256(str(value).casefold().encode()).hexdigest()[:16]
def read_config(path):
    text = path.read_text(encoding='utf-8-sig')
    return tomllib.loads(text) if path.suffix == '.toml' else json.loads(text)

def normalized(path):
    return os.path.normcase(os.path.normpath(str(path)))

def collect():
    objects, relations, issues = {}, [], []
    at = now()
    scope='environment'
    class Issues(list):
        def append(self,item):
            super().append({**item,'sourceKey':scope})
    issues=Issues()
    def add(kind, key, name, description='', **fields):
        oid = identity(kind, key)
        objects[oid] = dict(id=oid, kind=kind, name=name, description=description, source='本机扫描', checkedAt=at, status='已发现')
        objects[oid].update(fields)
        objects[oid]['sourceKey']=scope
        return oid
    def link(a, b, label):
        if a and b and a != b and not any(r['from']==a and r['to']==b for r in relations):
            relations.append({'from':a, 'to':b, 'label':label})
    def config(p):
        try:
            data=read_config(p) if p.is_file() else {}
            if not isinstance(data,dict):raise ValueError('配置根节点类型错误')
            return data
        except (OSError, ValueError) as exc:
            issues.append({'name':p.name,'reason':type(exc).__name__})
            return {}
    try:
        running = list(psutil.process_iter(['name','exe','pid']))
    except psutil.Error:
        running = []
    defs = [
        ('codex','Codex','开发与代码协作；本页汇总本地配置和可发现的能力。','.codex','OpenAI'),
        ('claude','Claude Code','终端里的代码助手，连接项目、技能与 MCP。','.claude','Anthropic'),
        ('pi','pi','轻量终端 Agent，可通过技能和扩展定制工作方式。','.pi','Pi'),
        ('herdr','Herdr','查看和协调 Agent 的工作状态。','.herdr','Herdr'),
        ('ccswitch','CCSwitch','统一管理 AI 工具的提供商、MCP 和 Skills。','.cc-switch','CC Switch')]
    agents = {}
    for command, name, desc, folder, vendor in defs:
        executable = shutil.which(command) if command != 'ccswitch' else None
        if command == 'ccswitch':
            for p in Path('D:/Envs/CCSwitch').glob('*.exe'):
                if 'switch' in p.name.lower(): executable=str(p);break
        directory = HOME/folder
        if not executable and not directory.exists(): continue
        procs=[p.info for p in running if p.info.get('name') and (p.info['name'].lower().split('.')[0] == command or (command=='ccswitch' and 'cc-switch' in p.info['name'].lower()))]
        aid=add('agent',command,name,desc,path=str(directory), executable=executable, vendor=vendor, processCount=len(procs), commandFound=bool(executable))
        objects[aid]['status']='运行中' if procs else ('入口可用' if executable else '发现配置')
        agents[command]=aid
    directories = {'.codex':('Codex 配置、插件与会话','codex'),'.claude':('Claude Code 配置与会话','claude'),'.pi':('pi 配置与会话','pi'),'.herdr':('Herdr 状态与配置','herdr'),'.cc-switch':('CCSwitch 配置与数据','ccswitch'),'.agents':('共享 Agent 技能与来源记录',None),'.cargo':('Rust 命令入口和依赖缓存',None),'.rustup':('Rust 编译工具链',None),'.vscode':('VS Code 扩展与用户级资源',None),'.cache':('多个工具共用的缓存，需按子目录判断',None),'.local':('本地命令和工具数据',None),'.dsh':('保留的共享配置；可能含语雀凭据',None),'.docker':('Docker 客户端配置与插件，不能仅凭目录判断安装状态',None)}
    directory_ids = {}
    for p in sorted(HOME.iterdir(),key=lambda x:x.name.casefold()):
        if not p.name.startswith('.') or not p.is_dir(): continue
        desc, owner = directories.get(p.name,('用途尚未确认，可在备注中补充。',None))
        try:
            entries=len(list(p.iterdir())) if not p.is_symlink() and not p.is_junction() else None
        except OSError:
            entries=None
            issues.append({'name':str(p),'reason':'目录不可读取'})
        did=add('directory',normalized(p),p.name,desc,path=str(p),entryCount=entries, ownerKnown=p.name in directories, sizeBytes=None)
        directory_ids[p.name]=did
        if owner: link(agents.get(owner),did,'使用目录')
    scope='agent-config'
    codex=config(HOME/'.codex/config.toml')
    disabled={normalized(x.get('path','')):x.get('enabled',True) for x in codex.get('skills',{}).get('config',[])}
    roots=[(HOME/'.agents/skills',['codex'],'共享技能'),(HOME/'.codex/skills',['codex'],'Codex 用户技能'),(HOME/'.codex/skills/.system',['codex'],'Codex 系统技能'),(HOME/'.claude/skills',['claude'],'Claude Code 用户技能'),(HOME/'.pi/agent/skills',['pi'],'pi 用户技能')]
    # Only explicitly configured plugins are represented as configured. Cache alone is not enablement.
    for key, settings in codex.get('plugins',{}).items():
        if not isinstance(settings,dict): continue
        name, _, market=key.partition('@')
        pid=add('plugin',key,name,'为 Agent 打包提供技能或工具。',enabled=settings.get('enabled',True),source='Codex 用户配置', path=str(HOME/'.codex/config.toml'), scope='用户')
        objects[pid]['status']='配置启用' if settings.get('enabled',True) else '已停用'
        link(agents.get('codex'),pid,'配置插件')
        base=HOME/'.codex/plugins/cache'/market/name
        if base.is_dir():
            versions=sorted((x for x in base.iterdir() if x.is_dir()),key=lambda x:x.stat().st_mtime,reverse=True)
            if versions: roots.append((versions[0]/'skills',['codex'],'插件附带:'+name))
    for base, owners, skill_scope in roots:
        if not base.is_dir():continue
        try: children=list(base.iterdir())
        except OSError:
            issues.append({'name':str(base),'reason':'技能目录不可读取'});continue
        for folder in children:
            p=folder/'SKILL.md'
            if not p.is_file(): continue
            try:
                raw=p.read_text(encoding='utf-8-sig')
                front=yaml.safe_load(raw.split('---',2)[1]) if raw.startswith('---') else {}
                if not isinstance(front,dict):front={}
            except (OSError,ValueError,yaml.YAMLError) as exc:
                issues.append({'name':str(p),'reason':type(exc).__name__});continue
            sid=add('skill',normalized(p.resolve()),str(front.get('name',folder.name)),str(front.get('description','没有提供用途说明。')),path=str(p),source=skill_scope,scope=skill_scope, enabled=disabled.get(normalized(p),True), declaredCompatibility=str(front.get('compatibility','')))
            objects[sid]['status']='已停用' if not objects[sid]['enabled'] else '已发现'
            for owner in owners:link(agents.get(owner),sid,'发现技能')
            if skill_scope.startswith('插件附带:'):
                for obj in list(objects.values()):
                    if obj['kind']=='plugin' and obj['name']==skill_scope.split(':',1)[1]:link(obj['id'],sid,'包含技能')
            first=folder.relative_to(HOME).parts[0] if folder.is_relative_to(HOME) else ''
            link(sid,directory_ids.get(first),'存放于')
    def mcps(entries,owner,source):
        if not isinstance(entries,dict):return
        for name, item in entries.items():
            if not isinstance(item,dict):continue
            enabled=item.get('enabled',True) and not item.get('disabled',False)
            command=item.get('command','')
            resolved=shutil.which(command) if command and not Path(command).is_absolute() else (command if command and Path(command).exists() else None)
            mid=add('mcp',str(source)+':'+name,name,'通过 MCP 向 Agent 提供工具；当前仅检查配置，未启动连接。',path=str(source),enabled=enabled,transport='HTTP' if item.get('url') else 'stdio',commandName=Path(command).name if command else '',commandExists=bool(resolved),source='用户配置',scope=owner,connection='未测试')
            objects[mid]['status']='配置启用' if enabled else '已停用'
            if command and not resolved and enabled:objects[mid]['status']='入口待检查'
            link(agents.get(owner),mid,'配置 MCP')
    mcps(codex.get('mcp_servers',{}),'codex',HOME/'.codex/config.toml')
    mcps(config(HOME/'.claude.json').get('mcpServers',{}),'claude',HOME/'.claude.json')
    scope='software-registry'
    # Registry enumeration is metadata only; never query Win32_Product.
    try:
        import winreg
        for hive, prefix in [(winreg.HKEY_LOCAL_MACHINE,'机器'),(winreg.HKEY_CURRENT_USER,'用户')]:
            for view in [winreg.KEY_WOW64_64KEY,winreg.KEY_WOW64_32KEY]:
                try: key=winreg.OpenKey(hive,r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',0,winreg.KEY_READ|view)
                except FileNotFoundError:continue
                except OSError:
                    issues.append({'name':prefix+'软件注册表','reason':'不可读取'});continue
                with key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            child=winreg.EnumKey(key,i)
                            with winreg.OpenKey(key,child) as sub:
                                def val(k):
                                    try:return winreg.QueryValueEx(sub,k)[0]
                                    except OSError:return ''
                                name=val('DisplayName')
                                if not name:continue
                                aid=add('software',prefix+':'+child+':'+str(view),name,'Windows 卸载注册表中登记的软件或组件。',version=str(val('DisplayVersion')),vendor=str(val('Publisher')),path=str(val('InstallLocation')),source=prefix+'级注册表',scope=prefix)
                                objects[aid]['status']='已登记'
                                objects[aid].update(registryHive='HKLM' if hive==winreg.HKEY_LOCAL_MACHINE else 'HKCU',registryView=view,registryKey=child,windowsInstaller=val('WindowsInstaller')==1)
                                objects[aid]['_displayIcon']=str(val('DisplayIcon'))
                        except OSError:
                            issues.append({'name':prefix+'软件记录','reason':'记录不可读取'});continue
    except ImportError:
        issues.append({'name':'Windows 软件','reason':'当前平台不支持注册表'})
    scope='icons'
    try:enrich_icons(list(objects.values()))
    except Exception:
        issues.append({'name':'软件图标','reason':'提取失败，清单仍可用'})
    scope='disks'
    disks=[]
    for part in psutil.disk_partitions():
        if 'cdrom' in part.opts:continue
        try:
            u=psutil.disk_usage(part.mountpoint)
            disks.append({'path':part.mountpoint,'total':u.total,'used':u.used,'free':u.free,'percent':u.percent})
        except OSError:continue
    return {'sources':[{'id':key,'status':'partial' if any(i.get('sourceKey')==key for i in issues) else 'success','checkedAt':at} for key in ['environment','agent-config','software-registry','icons','disks']], 'objects':list(objects.values()),'relations':relations,'issues':issues,'at':at,'machine':os.environ.get('COMPUTERNAME','本机'),'disks':disks,'scope':'Windows 当前用户与本机注册表；不含 WSL、所有项目级配置或云端账号插件。'}
