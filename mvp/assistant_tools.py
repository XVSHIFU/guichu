"""Task-scoped, read-only assistant tools. No network or configuration contents.

The caller fixes allowed_ids when creating the task; model arguments cannot add IDs.
Results are untrusted ordinary data, never instructions. Before external model use,
the caller must obtain consent covering object metadata, source/check timestamps,
relations and (when list_directory is enabled) current-level directory names.
This module performs no external transmission and does not grant that consent.
"""
import json
import os
from pathlib import Path


_TOOLS = {
    'search_objects': ('在任务已授权对象中搜索，最多返回20项', {'query': {'type': 'string'}}),
    'get_object': ('读取一个已授权对象的扫描元数据', {'object_id': {'type': 'string'}}),
    'get_relations': ('读取已授权对象之间的关系', {'object_id': {'type': 'string'}}),
    'read_config_summary': ('返回扫描中的配置摘要，不读取配置文件，连接未实测', {'object_id': {'type': 'string'}}),
    'list_directory': ('列出已授权目录当前层最多100个名称，不跟随链接或读取内容', {'object_id': {'type': 'string'}}),
}


def tools_catalog():
    return [{'type': 'function', 'function': {
        'name': name, 'description': description, 'strict': True,
        'parameters': {'type': 'object', 'properties': properties,
                       'required': list(properties), 'additionalProperties': False}}}
        for name, (description, properties) in _TOOLS.items()]


def _error(code, message):
    return {'error': {'code': code, 'message': message}}


def _text(value, limit=500):
    return value[:limit] if isinstance(value, str) else ''


def _evidence(obj):
    return {'object_id': _text(obj.get('id')), 'source': _text(obj.get('source')),
            'checked_at': _text(obj.get('checkedAt', obj.get('checked_at')))}


def _object(obj):
    # Never copy arbitrary nested metadata, commands, URLs, environment or headers.
    result = {key: _text(obj[key]) for key in ('id', 'name', 'kind', 'status', 'version', 'manualCategory') if key in obj}
    result['stale'] = obj.get('stale') is True
    result['evidence'] = _evidence(obj)
    return result


def execute_tool(name, args, objects, relations, allowed_ids):
    result = _execute_tool(name, args, objects, relations, allowed_ids)
    # UTF-8 budget also covers long names and multibyte characters.
    while len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > 32768:
        items = next((result[key] for key in ('objects', 'relations', 'entries') if result.get(key)), None)
        if items is None:
            return _error('result_too_large', '摘要超过输出限制')
        items.pop()
        result['truncated'] = True
    return result


def _execute_tool(name, args, objects, relations, allowed_ids):
    if not isinstance(name, str) or name not in _TOOLS:
        return _error('unknown_tool', '不支持此工具')
    fields = _TOOLS[name][1]
    if (not isinstance(args, dict) or set(args) != set(fields)
            or any(not isinstance(value, str) or len(value) > 500 for value in args.values())):
        return _error('invalid_arguments', '参数无效；不接受路径、命令或额外参数')
    # No missing-scope fallback to the full inventory.
    allowed = set(allowed_ids or [])
    scoped = {obj['id']: obj for obj in objects
              if isinstance(obj, dict) and isinstance(obj.get('id'), str) and obj['id'] in allowed}
    if name == 'search_objects':
        query = args['query'].casefold()
        found = [obj for obj in scoped.values()
                 if query in str(obj.get('name', '')).casefold() or query in str(obj.get('kind', '')).casefold()]
        return {'objects': [{'id': _text(obj['id']), 'name': _text(obj.get('name')),
                             'evidence': _evidence(obj)} for obj in found[:20]], 'truncated': len(found) > 20}
    obj = scoped.get(args['object_id'])
    if obj is None:
        return _error('object_unavailable', '对象不在任务授权范围内，或已不在当前扫描中')
    if name == 'get_object':
        return _object(obj)
    if name == 'get_relations':
        found = [relation for relation in relations if isinstance(relation, dict)
                 and relation.get('from') in scoped and relation.get('to') in scoped
                 and obj['id'] in (relation.get('from'), relation.get('to'))]
        return {'relations': [{'from': relation['from'], 'to': relation['to'],
                              'label': _text(relation.get('label')),
                              'basis': '人工记录' if relation.get('manual') else '扫描发现',
                              'evidence': [_evidence(scoped[relation['from']]), _evidence(scoped[relation['to']])]}
                             for relation in found[:100]],
                'truncated': len(found) > 100, 'evidence': _evidence(obj)}
    if name == 'read_config_summary':
        summary = {key: obj[key] for key in ('enabled', 'commandExists') if isinstance(obj.get(key), bool)}
        if obj.get('transport') in ('HTTP', 'stdio', 'http', 'sse', 'streamable-http'):
            summary['transport'] = obj['transport']
        return {'summary': summary, 'connection': '未实测', 'basis': '当前扫描元数据，未读取配置正文',
                'stale': obj.get('stale') is True, 'evidence': _evidence(obj)}
    if obj.get('kind') != 'directory':
        return _error('not_directory', '此对象不是已收录的目录')
    raw = obj.get('path')
    if not isinstance(raw, str) or raw.startswith(('\\\\', '//')) or not Path(raw).is_absolute():
        return _error('invalid_directory', '仅支持本机绝对目录路径')
    try:
        path = Path(raw)
        if any(component.is_symlink() or component.is_junction() for component in (path, *path.parents)):
            return _error('linked_directory', '不跟随链接目录')
        entries = []
        with os.scandir(path) as iterator:
            for entry in iterator:
                if len(entries) == 100:
                    return {'entries': entries, 'truncated': True, 'evidence': _evidence(obj)}
                link = entry.is_symlink() or Path(entry.path).is_junction()
                entries.append({'name': entry.name, 'directory': entry.is_dir(follow_symlinks=False), 'link': link})
        return {'entries': entries, 'truncated': False, 'evidence': _evidence(obj)}
    except (OSError, ValueError):
        return _error('directory_unavailable', '目录不存在、无读取权限或已断开；请重新检查对象')
