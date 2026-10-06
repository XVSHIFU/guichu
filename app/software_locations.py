"""Discover local installation/configuration metadata without executing software.

Name matches are candidates, never proof that a folder is owned by a product.
"""
import hashlib
import os
from pathlib import Path
import re
from package_inventory import local


def normalized(value):
    return os.path.normcase(os.path.normpath(str(value)))


def product_name(value):
    return re.sub(r'[\W_\d]+', '', str(value).casefold())


def automatic_sources(disks):
    roots = [os.environ.get(k) for k in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA')]
    roots = [Path(p)/'Programs' if p == os.environ.get('LOCALAPPDATA') else Path(p) for p in roots if p]
    for disk in disks:
        roots.extend(Path(disk['path'])/name for name in ('ProgramAll', 'Apps', 'Tools'))
    seen = set()
    for root in roots:
        try:
            local(root)
            if not root.is_dir() or normalized(root) in seen: continue
            seen.add(normalized(root))
            yield {'id': 'auto-' + hashlib.sha256(normalized(root).encode()).hexdigest()[:16], 'path': str(root), 'type': 'portable', 'label': root.name}
        except (OSError, ValueError): continue


def enrich_locations(data):
    tools = [o for o in data['objects'] if o['kind'] in ('software', 'agent')]
    # Inspect registered install directories, never launch discovered executables.
    for obj in tools:
        if not obj.get('registryKey') or not obj.get('path'): continue
        try:
            root = local(obj['path'])
            matches = []
            with os.scandir(root) as entries:
                for i, entry in enumerate(entries):
                    if i >= 200: break
                    if Path(entry.name).suffix.casefold() == '.exe' and product_name(Path(entry.name).stem) == product_name(obj['name']):
                        p = local(entry.path)
                        if p.is_file(): matches.append(str(p))
            if len(matches) == 1: obj['executable'] = matches[0]
        except (OSError, ValueError): pass
    roots = [Path(p) for p in [os.environ.get('APPDATA'), os.environ.get('LOCALAPPDATA'), os.environ.get('PROGRAMDATA')] if p]
    roots += [Path.home(), Path.home()/'.config', Path.home()/'Documents']
    folders = []
    for root in roots:
        try:
            local(root)
            with os.scandir(root) as entries:
                for i, entry in enumerate(entries):
                    if i >= 1500: break
                    if root == Path.home() and not entry.name.startswith('.'): continue
                    try:
                        p = local(entry.path)
                        if entry.is_dir(follow_symlinks=False): folders.append(p)
                    except (OSError, ValueError): continue
        except (OSError, ValueError): continue
    for obj in tools:
        locations = []
        def add(role, path, basis, confidence='observed'):
            if not path: return
            try:
                p = local(path)
                if p.exists() and not any(row['path']==str(p) and row['role']==role for row in locations):
                    locations.append({'role': role, 'path': str(p), 'basis': basis, 'confidence': confidence})
            except (OSError, ValueError): pass
        if obj['kind'] == 'agent':
            add('config', obj.get('path'), '已知产品配置位置')
            if not obj.get('executable'):
                candidates = {o.get('executable') or o.get('path') for o in tools if o['kind']=='software' and product_name(o['name'])==product_name(obj['name']) and (o.get('executable') or o.get('portable'))}
                if len(candidates)==1:
                    obj['executable']=next(iter(candidates))
                    obj['commandFound']=True
                    if obj.get('status') == '发现配置': obj['status'] = '入口已找到'
            add('entry', obj.get('executable'), 'PATH 或注册表程序入口')
        elif obj.get('managerRecord'):
            add('install', obj.get('path'), obj.get('managedChannel','')+' 管理目录')
        elif obj.get('packageFamily'):
            add('install', obj.get('path'), 'Windows 应用包安装位置')
        elif obj.get('distribution'):
            add('metadata' if obj['distribution']=='pip' else 'install', obj.get('path'), '安装包元数据位置')
            add('environment', obj.get('installPath'), '包环境目录')
        elif obj.get('portable'):
            add('entry', obj.get('path'), '扫描到的 EXE 文件，未执行')
        else:
            add('install', obj.get('path'), '注册表 InstallLocation')
            add('entry', obj.get('executable'), '安装目录内与产品同名的程序文件，未执行')
            add('icon', obj.get('registryExecutable'), '注册表图标资源，不视为主程序入口')
        for location in list(locations):
            if location['role']=='entry': add('install', str(Path(location['path']).parent), '程序入口所在目录', location['confidence'])
        names = {product_name(obj['name'])}
        if obj.get('packageName'): names.add(product_name(obj['packageName'].split('/')[-1]))
        names = {n for n in names if len(n)>=4}
        for folder in folders:
            if product_name(folder.name) in names:
                add('config', str(folder), '用户数据目录与产品名称匹配，内容与归属未验证', 'candidate')
            vendor=product_name(obj.get('vendor',''))
            if len(vendor)>=5 and product_name(folder.name)==vendor:
                add('config', str(folder), '发布者同名数据目录，可能由多个软件共用', 'candidate')
        # Portable applications often keep configuration beside the executable.
        for location in list(locations):
            if location['role']=='install':
                for name in ('config', 'data', 'user-data'):
                    add('config', str(Path(location['path'])/name), '程序目录下常见数据目录，归属与用途未验证', 'candidate')
        obj['locations'] = locations[:30]
        obj['locationCoverage'] = '注册表、已知入口与常见数据目录；每个安装目录最多200项、每个数据根目录最多1500项。不可读或无匹配不代表不存在其他位置'
        if not obj.get('path'):
            observed = next((x for x in locations if x['role']=='install'), None)
            if observed: obj['installPath'] = observed['path']
    # Collapse only duplicate evidence, retaining all original IDs and records.
    seen = {}
    for obj in tools:
        obj.pop('duplicateOf', None)
        key = None
        if obj.get('registryKey'):
            if obj.get('path') and obj.get('vendor') and obj.get('version'):
                key = ('installation', obj.get('registryHive'), obj['name'].casefold(), obj['vendor'].casefold(), obj['version'], normalized(obj['path']))
            else:
                key = ('registry', obj.get('registryHive'), obj['registryKey'].casefold(), obj.get('version'), normalized(obj.get('path','')))
        elif obj.get('portable'):
            key = ('entry', normalized(obj.get('path','')))
        if key is not None:
            if key in seen:
                primary=seen[key]
                obj['duplicateOf']=primary['id']
                if not primary.get('iconUrl') and obj.get('iconUrl'): primary['iconUrl']=obj['iconUrl']
                edge={'from':primary['id'],'to':obj['id'],'label':'同一安装的另一来源记录'}
                if edge not in data['relations']:data['relations'].append(edge)
            else: seen[key]=obj
    return data
