"""Bounded, metadata-only discovery for explicitly registered local roots.

Portable discovery checks only root/one child directory. Project discovery reads
only .codex/config.toml and .mcp.json; configuration values are allowlisted and
never executed. Each registered source is an independent reconciliation group.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tomllib

MAX_ENTRIES = 500
MAX_EXECUTABLES = 100
MAX_MCPS = 200
MAX_CONFIG_BYTES = 2 * 1024 * 1024


def _identity(kind, value):
    return kind + ':' + hashlib.sha256(str(value).casefold().encode()).hexdigest()[:16]


def _local(path):
    path = Path(path)
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise ValueError('仅支持本机绝对路径')
    if any(part.is_symlink() or part.is_junction() for part in (path, *path.parents)):
        raise ValueError('不跟随链接路径')
    return path


def _config(path):
    path = _local(path)
    try:
        metadata = path.stat()
    except FileNotFoundError:
        return {}
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_CONFIG_BYTES:
        raise ValueError('配置不是普通文件或超过读取上限')
    with path.open('rb') as stream:
        raw = stream.read(MAX_CONFIG_BYTES + 1)
    if len(raw) > MAX_CONFIG_BYTES:
        raise ValueError('配置超过读取上限')
    text = raw.decode('utf-8-sig')
    result = tomllib.loads(text) if path.suffix == '.toml' else json.loads(text)
    if not isinstance(result, dict):
        raise ValueError('配置根节点无效')
    return result


def collect_registered(sources):
    result = {'objects': [], 'relations': [], 'issues': [], 'sources': []}
    checked_at = datetime.now(timezone.utc).isoformat()
    for source in sources:
        key = 'registered:' + str(source.get('id', ''))
        state = {'id': key, 'status': 'success', 'checkedAt': checked_at}
        result['sources'].append(state)
        def issue(reason):
            state['status'] = 'partial'
            item = {'sourceKey': key, 'name': '登记来源', 'reason': reason}
            if item not in result['issues']:
                result['issues'].append(item)
        def add(kind, identity, name, **fields):
            obj = {'id': _identity(kind, key + ':' + str(identity)), 'kind': kind, 'name': name,
                   'sourceKey': key, 'checkedAt': checked_at, **fields}
            result['objects'].append(obj)
            return obj['id']
        try:
            raw = source.get('path')
            if not isinstance(raw, str) or len(raw) > 4096:
                raise ValueError('路径无效')
            root = _local(raw).resolve(strict=True)
            if not root.is_dir():
                raise ValueError('来源不是目录')
            kind = source.get('type')
            if kind not in ('portable', 'project'):
                raise ValueError('来源类型无效')
            label = source.get('label')
            name = label[:200] if isinstance(label, str) and label else root.name or str(root)
            source_name = '登记的便携目录' if kind == 'portable' else '登记的项目配置'
            directory_id = add('directory', os.path.normcase(str(root)), name, path=str(root),
                               source=source_name, scope=kind, status='目录已登记')
            if kind == 'portable':
                pending = [(root, 0)]
                entries_seen = executables = 0
                limited = False
                while pending and not limited:
                    directory, depth = pending.pop(0)
                    try:
                        _local(directory)
                        with os.scandir(directory) as entries:
                            for entry in entries:
                                if entries_seen >= MAX_ENTRIES:
                                    issue('已达到500项检查上限，结果不完整')
                                    limited = True
                                    break
                                entries_seen += 1
                                if entry.is_symlink() or Path(entry.path).is_junction():
                                    issue('链接项已跳过，结果不完整')
                                    continue
                                if entry.is_dir(follow_symlinks=False):
                                    if depth == 0:
                                        pending.append((Path(entry.path), 1))
                                elif Path(entry.name).suffix.casefold() == '.exe':
                                    metadata = os.stat(entry.path, follow_symlinks=False)
                                    if not stat.S_ISREG(metadata.st_mode):
                                        continue
                                    if executables >= MAX_EXECUTABLES:
                                        issue('已达到100个入口上限，结果不完整')
                                        limited = True
                                        break
                                    executable_id = add('software', os.path.normcase(entry.path),
                                                        Path(entry.name).stem, path=entry.path,
                                                        source=source_name, scope='portable',
                                                        status='入口已发现', portable=True,
                                                        sizeBytes=metadata.st_size, _displayIcon=entry.path)
                                    result['relations'].append({'from': executable_id, 'to': directory_id, 'label': '登记于'})
                                    executables += 1
                    except (OSError, ValueError):
                        issue('部分目录或入口不可读取，结果不完整')
            else:
                mcp_count = 0
                for config_path, field in ((root / '.codex' / 'config.toml', 'mcp_servers'),
                                           (root / '.mcp.json', 'mcpServers')):
                    try:
                        config = _config(config_path)
                        servers = config.get(field, {})
                        if not isinstance(servers, dict):
                            raise ValueError('MCP映射无效')
                        for server_name, settings in servers.items():
                            if mcp_count >= MAX_MCPS:
                                issue('已达到200个MCP上限，结果不完整')
                                break
                            if not isinstance(server_name, str) or len(server_name) > 256:
                                issue('部分MCP名称超过长度限制，结果不完整')
                                continue
                            if not isinstance(settings, dict):
                                issue('部分MCP配置格式无效，结果不完整')
                                continue
                            enabled = settings.get('enabled', True)
                            disabled = settings.get('disabled', False)
                            if type(enabled) is not bool or type(disabled) is not bool:
                                issue('部分MCP开关格式无效，结果不完整')
                                continue
                            command = settings.get('command', '')
                            command_name = Path(command).name if isinstance(command, str) else ''
                            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', command_name):
                                command_name = ''
                            mid = add('mcp', str(config_path) + ':' + server_name, server_name,
                                      path=str(config_path), source=source_name, scope='project',
                                      enabled=enabled and not disabled,
                                      transport='HTTP' if settings.get('url') else 'stdio',
                                      commandName=command_name, connection='未测试',
                                      status='配置启用' if enabled and not disabled else '已停用')
                            result['relations'].append({'from': mid, 'to': directory_id, 'label': '配置位于'})
                            mcp_count += 1
                    except (OSError, ValueError, UnicodeError):
                        issue('项目配置不可读取、格式无效或超过上限，结果不完整')
        except (OSError, ValueError):
            issue('登记目录不可用或属于链接/网络路径，未完成检查')
    return result
