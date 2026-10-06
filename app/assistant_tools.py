"""Task-scoped, read-only assistant tools. No network or configuration contents.

The caller fixes allowed_ids when creating the task; model arguments cannot add IDs.
Results are untrusted ordinary data, never instructions. Before external model use,
the caller must obtain consent covering object metadata, source/check timestamps,
relations and (when list_directory is enabled) current-level directory names.
This module performs no external transmission and does not grant that consent.
"""
import json
import hashlib
import directory_browser
from pathlib import Path


PAGE_SIZE = 20
_CURSOR = {'type': 'string', 'description': '首次查询传空字符串 ""；仅在 next_cursor 为非空字符串时原样续查，null 表示没有下一页。不要传字符串 "null"，不得自行构造'}

_TOOLS = {
    'search_objects': ('在本次授权清单按名称或种类搜索，每页最多20项；相同 query 携 next_cursor 续查', {'query': {'type': 'string'}, 'cursor': _CURSOR}),
    'get_object': ('读取一个已授权对象的扫描元数据', {'object_id': {'type': 'string'}}),
    'get_relations': ('读取已授权对象之间的关系，每页最多20项；相同 object_id 携 next_cursor 续查', {'object_id': {'type': 'string'}, 'cursor': _CURSOR}),
    'read_config_summary': ('返回扫描中的配置摘要，不读取配置文件，连接未实测', {'object_id': {'type': 'string'}}),
    'list_directory': ('列出授权目录当前层名称，每页最多20项；同一 object_id 携非空字符串 next_cursor 续查，null 表示没有下一页；是否完整还须检查 read_errors/enumeration_complete。无文件名前缀筛选。游标120秒有效；变化或过期时以 cursor="" 重查并丢弃旧页；不读取内容、不接受路径', {'object_id': {'type': 'string'}, 'cursor': _CURSOR}),
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
    result = {key: _text(obj[key]) for key in ('id', 'name', 'kind', 'status', 'version', 'manualCategory', 'configurationStatus', 'agentIdentity', 'identityEvidence', 'entryRole', 'installDrive', 'distribution', 'locationCoverage', 'duplicateOf', 'installationForm', 'productId', 'packageFamily', 'appxName', 'systemComponentBasis', 'systemComponentAdvice') if key in obj}
    result['locations'] = [{k:_text(row.get(k),500) for k in ('role','path','basis','confidence')} for row in obj.get('locations',[])[:30]]
    origin = obj.get('softwareOrigin', {})
    result['softwareOrigin'] = {k: _text(origin.get(k), 100) for k in ('channel', 'method', 'download')}
    result['softwareOrigin']['manualFields'] = [k for k in origin.get('manualFields', []) if k in ('channel', 'method', 'download')]
    result['softwareOrigin']['evidence'] = [_text(v,300) for v in origin.get('evidence',[])[:8]]
    result['capabilities'] = [v for v in obj.get('capabilities', []) if v in ('software', 'agent')]
    result['applicationEntries'] = [{k:_text(entry.get(k),200) for k in ('name','appId')} for entry in obj.get('applicationEntries',[])[:20]]
    result['commands'] = [_text(v, 200) for v in obj.get('commands', [])[:30]]
    result['systemComponent'] = obj.get('systemComponent') is True
    result['stale'] = obj.get('stale') is True
    result['stale_basis'] = 'stale 仅表示失败扫描保留了旧记录；false 不表示新鲜或实时验证'
    result['evidence'] = _evidence(obj)
    result['observations'] = {key: obj[key] for key in
                              ('enabled', 'commandFound', 'commandExists')
                              if type(obj.get(key)) is bool}
    if type(obj.get('processCount')) is int and obj['processCount'] >= 0:
        result['observations']['processCount'] = obj['processCount']
        result['observations']['process_basis'] = '扫描时按进程名称匹配，未验证进程身份或当前运行状态'
    if obj.get('kind') == 'agent':
        process = obj.get('processObservation')
        count = obj.get('processCount')
        result['observations']['processCount'] = count if type(count) is int and count >= 0 else None
        if isinstance(process, dict):
            result['process'] = {key:_text(process.get(key)) for key in ('state','coverage','reason','observed_at')}
            result['process'].update({key:process[key] for key in ('observed_matches','unreadable_count')
                                      if type(process.get(key)) is int and process[key] >= 0})
        else:
            result['process'] = {'state':'not_checked' if 'processCount' not in obj else 'matched' if type(count) is int and count > 0 else 'unknown',
                                 'coverage':'unknown', 'observed_at':_evidence(obj)['checked_at'],
                                 'reason':'旧记录未提供进程读取覆盖范围或失败原因；零值不能证明完整枚举未发现'}
    result['scope'] = _text(obj.get('scope'))
    result['current_state'] = '未实时验证；状态与观察值仅对应 evidence.checked_at'
    return result


def execute_tool(name, args, objects, relations, allowed_ids):
    result = _execute_tool(name, args, objects, relations, allowed_ids)
    return result


def _inventory_page(items, key, cursor, binding, metadata):
    # Task inventory is fixed by the runtime. Bind continuation to its contents,
    # query and authorization so a changed inventory cannot silently shift pages.
    fingerprint = hashlib.sha256(json.dumps([binding,items], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    offset = 0
    if cursor is not None:
        try:
            digest, raw_offset = cursor.split(':')
            offset = int(raw_offset)
            if digest != fingerprint or not 0 < offset < len(items):raise ValueError()
        except (ValueError, AttributeError):
            return _error('cursor_expired', '查询范围或清单已变化，或游标无效；以 cursor="" 重查并丢弃旧页')
    page = []
    result = {**metadata, key:page, 'next_cursor':None, 'truncated':False,
              'scope_notice':'本次授权清单的固定视图，不是实时全机状态；仅在 next_cursor 为非空字符串时保持查询参数继续，null 表示没有下一页；仍有截断提示时不能声称结果完整'}
    for item in items[offset:offset+PAGE_SIZE]:
        # Reserve space for cursor and metadata; do not drop items after creating
        # a cursor, which would make the omitted range impossible to retrieve.
        if len(json.dumps({**result,key:page+[item]}, ensure_ascii=False).encode()) > 32000:break
        page.append(item)
    if not page and offset < len(items):return _error('result_too_large', '单项摘要超过限制，无法返回')
    next_offset = offset + len(page)
    if next_offset < len(items):
        result.update(next_cursor=f'{fingerprint}:{next_offset}', truncated=True)
    return result


def _execute_tool(name, args, objects, relations, allowed_ids):
    if not isinstance(name, str) or name not in _TOOLS:
        return _error('unknown_tool', '不支持此工具')
    fields = _TOOLS[name][1]
    if (not isinstance(args, dict) or set(args) - set(fields) or (set(fields) - {'cursor'}) - set(args)
            or any(not (key == 'cursor' and value is None) and (not isinstance(value, str) or len(value) > 500) for key, value in args.items())):
        return _error('invalid_arguments', '参数无效；不接受路径、命令或额外参数')
    # No missing-scope fallback to the full inventory.
    allowed = set(allowed_ids or [])
    scoped = {obj['id']: obj for obj in objects
              if isinstance(obj, dict) and isinstance(obj.get('id'), str) and obj['id'] in allowed}
    cursor = args.get('cursor') or None  # Missing/null accepted for pre-pagination callers.
    if name == 'search_objects':
        query = args['query'].casefold()
        found = [obj for obj in scoped.values()
                 if any(query in str(value).casefold() for value in
                        (obj.get('name', ''), 'software' if obj.get('capabilities') and obj.get('kind') in ('software','agent') else obj.get('kind', ''), obj.get('packageName', ''),
                         *obj.get('capabilities', []), *obj.get('commands', [])))]
        return _inventory_page([_object(obj) for obj in found], 'objects', cursor,
                               (name, query, sorted(allowed)),
                               {'matched_count':len(found), 'scope':'仅本次授权清单；未匹配不证明本机不存在'})
    obj = scoped.get(args['object_id'])
    if obj is None:
        return _error('object_unavailable', '对象不在任务授权范围内，或已不在当前扫描中')
    if name == 'get_object':
        return _object(obj)
    if name == 'get_relations':
        found = [relation for relation in relations if isinstance(relation, dict)
                 and relation.get('from') in scoped and relation.get('to') in scoped
                 and obj['id'] in (relation.get('from'), relation.get('to'))]
        items = [{'from': relation['from'], 'to': relation['to'],
                              'label': _text(relation.get('label')),
                              'basis': '人工记录' if relation.get('manual') else '扫描发现',
                              'interpretation': '用户建立的关联，不证明实际调用' if relation.get('manual') else '配置或已知位置形成的自动关联，不证明实际使用、加载或调用',
                              'evidence': [_evidence(scoped[relation['from']]), _evidence(scoped[relation['to']])]}
                             for relation in found]
        return _inventory_page(items, 'relations', cursor, (name, obj['id'], sorted(allowed)),
                               {'matched_count':len(found), 'evidence':_evidence(obj)})
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
    result, status = directory_browser.browse_directory(
        {'path':raw, 'cursor':cursor}, page_size=PAGE_SIZE,
        binding=('assistant', obj['id'], tuple(sorted(allowed))), validate_changes=True)
    if status != 200:
        message=result['error']
        if status==409:message+='；请保持 object_id，将 cursor 设为空字符串 "" 重查，不要传字符串 "null"'
        return _error(result.get('code', 'directory_unavailable'), message)
    more = result['next'] is not None
    return {'entries':[{key:entry[key] for key in ('name','directory','link')} for entry in result['entries']],
            'next_cursor':result['next'], 'truncated':more or result['read_errors'] > 0,
            'enumeration_complete':result['read_errors'] == 0, 'read_errors':result['read_errors'],
            'observed_count':result['total'], 'observed_at':result['observed_at'], 'evidence':_evidence(obj),
            'basis':'本次实时列举保存的分页；evidence.checked_at 仅为目录对象的收录时间',
            'scope':'当前层，不递归；分页复用同一次枚举，非文件系统原子快照，变化检查也不能排除所有并发改动',
            'continuation':'首次 cursor=""；仅在 next_cursor 为非空字符串时用相同 object_id 续查，null 表示没有下一页。完整性仍须检查 read_errors=0、enumeration_complete=true、所有页已取得且无其他截断。过期或目录变化则丢弃旧页重查。无文件名前缀筛选。'}
