"""Remove one Claude Code user MCP registration; restore exact original bytes.

Claude has no generic enabled flag in this file. Removal is explicit, reversible,
and never changes project registrations or runs the registered command.
Configuration scope reference: https://code.claude.com/docs/en/mcp#user-scope
"""
import copy
import json
import os
import uuid
import mcp_config_action as files

_read = files._read

def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('重复 JSON 键，拒绝改写')
        result[key] = value
    return result

def _render(raw, server_id, enabled):
    if enabled is not False:
        raise ValueError('仅支持移除此注册；恢复须使用原始备份')
    data = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_pairs)
    if not isinstance(data, dict) or not isinstance(data.get('mcpServers'), dict) or not isinstance(data['mcpServers'].get(server_id), dict):
        raise ValueError('不是独立的用户 MCP 注册')
    del data['mcpServers'][server_id]
    after = (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode('utf-8')
    return {'before_enabled':True, 'before_hash':files._hash(raw), 'after_hash':files._hash(after)}, after

def preview(path, server_id, enabled):
    return _render(_read(path), server_id, enabled)[0]

def apply(path, server_id, enabled, expected_hash, backup_dir, on_backup=None):
    with files._LOCK:
        before = _read(path)
        if files._hash(before) != expected_hash:
            raise ValueError('配置已变化，请重新预览')
        summary, after = _render(before, server_id, enabled)
        directory = files._safe_path(backup_dir)
        directory.mkdir(parents=True, exist_ok=True)
        backup = directory / (uuid.uuid4().hex+'.json.bak')
        with backup.open('xb') as stream:
            if os.name == 'nt':
                private = files._private_dacl()
                files._set_dacl(backup, private)
                if files._dacl(backup).replace('D:PAI','D:P',1) != private:
                    raise ValueError('备份权限校验失败')
            else:
                os.chmod(backup, 0o600)
            stream.write(before)
            stream.flush()
            os.fsync(stream.fileno())
        if files._hash(_read(backup)) != summary['before_hash']:
            raise ValueError('备份校验失败')
        receipt = {**summary, 'backup_path':str(backup), 'path':str(files._safe_path(path))}
        try:
            if on_backup:
                on_backup(copy.deepcopy(receipt))
            files._replace(path, after, expected_hash)
        except Exception as exc:
            exc.receipt = receipt
            raise
        return receipt

restore = files.restore
