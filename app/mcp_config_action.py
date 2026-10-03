"""Single standalone MCP enabled edit; never exposed as an arbitrary-path API.

The future server must resolve/authorize path and server_id from a fixed object.
Receipts and backup paths are trusted server records, not client supplied data.
File hashes detect conflicts; this process lock cannot exclude external editors.
"""
import copy
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
import tomllib
import uuid

MAX_BYTES = 2 * 1024 * 1024
_LOCK = threading.RLock()


def _windows_api():
    api = ctypes.WinDLL('advapi32', use_last_error=True)
    api.GetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
                                        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    api.GetNamedSecurityInfoW.restype = wintypes.DWORD
    api.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [ctypes.c_void_p, wintypes.DWORD,
        wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    api.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    api.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    api.GetSecurityDescriptorControl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD)]
    api.SetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    api.SetNamedSecurityInfoW.restype = wintypes.DWORD
    api.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    api.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    api.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    api.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    return api


def _free(pointer):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    kernel.LocalFree(pointer)


def _dacl(path):
    api = _windows_api()
    descriptor, text = ctypes.c_void_p(), ctypes.c_void_p()
    result = api.GetNamedSecurityInfoW(str(path), 1, 4, None, None, None, None, ctypes.byref(descriptor))
    if result:
        raise ctypes.WinError(result)
    try:
        if not api.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, 1, 4, ctypes.byref(text), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return ctypes.wstring_at(text)
    finally:
        _free(text)
        _free(descriptor)


def _set_dacl(path, sddl):
    api = _windows_api()
    descriptor, acl = ctypes.c_void_p(), ctypes.c_void_p()
    if not api.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        present, defaulted = wintypes.BOOL(), wintypes.BOOL()
        control, revision = wintypes.WORD(), wintypes.DWORD()
        if not api.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(acl), ctypes.byref(defaulted)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not present.value or not acl.value:
            raise ValueError('拒绝缺失或无限制DACL')
        if not api.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)):
            raise ctypes.WinError(ctypes.get_last_error())
        flags = 4 | (0x80000000 if control.value & 0x1000 else 0x20000000)
        # SetFileSecurity preserves existing ACE/control bits without recomputing
        # auto-inheritance, unlike SetNamedSecurityInfo for an unprotected DACL.
        if not api.SetFileSecurityW(str(path), flags, descriptor):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        _free(descriptor)


def _private_dacl():
    api = _windows_api()
    token, text = wintypes.HANDLE(), ctypes.c_void_p()
    if not api.OpenProcessToken(wintypes.HANDLE(-1), 8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = wintypes.DWORD()
        api.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not api.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        if not api.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        sddl = 'D:P(A;;FA;;;SY)(A;;FA;;;' + ctypes.wstring_at(text) + ')'
        # Windows may serialize well-known account SIDs as aliases (for example LA).
        # Round-trip the expected descriptor through the same Windows serializer.
        descriptor, canonical = ctypes.c_void_p(), ctypes.c_void_p()
        try:
            if not api.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
                raise ctypes.WinError(ctypes.get_last_error())
            if not api.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, 1, 4, ctypes.byref(canonical), None):
                raise ctypes.WinError(ctypes.get_last_error())
            return ctypes.wstring_at(canonical)
        finally:
            _free(canonical)
            _free(descriptor)
    finally:
        _free(text)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(token)


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _safe_path(path):
    path = Path(path).absolute()
    if str(path).startswith(('\\\\', '//')):
        raise ValueError('仅支持本机普通配置文件')
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError('不支持链接路径')
    return path


def _read(path):
    path = _safe_path(path)
    if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size > MAX_BYTES:
        raise ValueError('配置不是普通文件或超过2MB')
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('配置超过2MB')
    return raw


def _render(raw, server_id, enabled):
    if not isinstance(server_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', server_id):
        raise ValueError('首版仅支持简单名称的独立MCP表')
    if type(enabled) is not bool:
        raise ValueError('enabled必须为布尔值')
    try:
        text = raw.decode('utf-8')
        before = tomllib.loads(text)
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError('配置不是有效UTF-8 TOML') from exc
    # Reject syntax whose line-like contents could masquerade as a table header.
    if '"""' in text or "'''" in text:
        raise ValueError('暂不支持包含多行字符串的配置')
    servers = before.get('mcp_servers', {})
    config = servers.get(server_id) if isinstance(servers, dict) else None
    if not isinstance(config, dict):
        raise ValueError('目标MCP表不存在')
    if 'enabled' in config and type(config['enabled']) is not bool:
        raise ValueError('原enabled不是布尔值')
    lines = text.splitlines(keepends=True)
    header = re.compile(r'^[ \t]*\[[ \t]*mcp_servers\.' + re.escape(server_id) + r'[ \t]*\][ \t]*(?:#[^\r\n]*)?(?:\r?\n)?$')
    starts = [i for i, line in enumerate(lines) if header.fullmatch(line)]
    if len(starts) != 1:
        raise ValueError('无法明确定位独立MCP表')
    start = starts[0]
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith('[')), len(lines))
    field = re.compile(r'^([ \t]*enabled[ \t]*=[ \t]*)(true|false)([ \t]*(?:#[^\r\n]*)?)(\r?\n)?$')
    found = [(i, field.fullmatch(lines[i])) for i in range(start + 1, end) if field.fullmatch(lines[i])]
    if len(found) > 1 or ('enabled' in config and len(found) != 1):
        raise ValueError('无法明确定位唯一enabled字段')
    value = 'true' if enabled else 'false'
    if found:
        i, match = found[0]
        lines[i] = match[1] + value + match[3] + (match[4] or '')
    else:
        newline = '\r\n' if '\r\n' in text else '\n'
        if not lines[start].endswith('\n'):
            lines[start] += newline
        lines.insert(start + 1, 'enabled = ' + value + newline)
    after_bytes = ''.join(lines).encode('utf-8')
    if len(after_bytes) > MAX_BYTES:
        raise ValueError('修改后的配置超过2MB')
    try:
        after = tomllib.loads(after_bytes.decode('utf-8'))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError('修改后的TOML校验失败') from exc
    expected = copy.deepcopy(before)
    expected['mcp_servers'][server_id]['enabled'] = enabled
    if after != expected:
        raise ValueError('修改涉及目标enabled以外的字段')
    return {'before_hash': _hash(raw), 'after_hash': _hash(after_bytes),
            'before_enabled': config.get('enabled'), 'after_enabled': enabled}, after_bytes


def preview(path, server_id, enabled):
    return _render(_read(path), server_id, enabled)[0]


def _replace(path, raw, expected_hash):
    path = _safe_path(path)
    original_dacl = _dacl(path) if os.name == 'nt' else None
    descriptor, temporary = tempfile.mkstemp(prefix='.mcp-config-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            if original_dacl is not None:
                _set_dacl(temporary, original_dacl)
                if _dacl(temporary) != original_dacl:
                    raise ValueError('临时文件DACL无法完整保留')
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if _hash(_read(path)) != expected_hash:
            raise ValueError('配置已变化，请重新预览')
        os.replace(temporary, path)
        if _read(path) != raw:
            raise ValueError('写后校验失败；请检查恢复记录')
        if original_dacl is not None and _dacl(path) != original_dacl:
            raise ValueError('写后DACL校验失败；请检查恢复记录')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply(path, server_id, enabled, expected_hash, backup_dir, on_backup=None):
    with _LOCK:
        before = _read(path)
        if _hash(before) != expected_hash:
            raise ValueError('配置已变化，请重新预览')
        summary, after = _render(before, server_id, enabled)
        directory = _safe_path(backup_dir)
        directory.mkdir(parents=True, exist_ok=True)
        backup = directory / (uuid.uuid4().hex + '.toml.bak')
        # Exclusive creation prevents overwriting an existing backup.
        with backup.open('xb') as stream:
            if os.name == 'nt':
                private = _private_dacl()
                _set_dacl(backup, private)
                if _dacl(backup).replace('D:PAI', 'D:P', 1) != private:
                    raise ValueError('备份权限校验失败')
            stream.write(before)
            stream.flush()
            os.fsync(stream.fileno())
        if _hash(_read(backup)) != summary['before_hash']:
            raise ValueError('备份校验失败')
        receipt = {**summary, 'backup_path': str(backup), 'path': str(_safe_path(path))}
        try:
            if on_backup is not None:
                on_backup(copy.deepcopy(receipt))
            _replace(path, after, expected_hash)
        except Exception as exc:
            # Preserve recovery evidence even if replacement or its verification fails.
            exc.receipt = receipt
            raise
        return receipt


def restore(path, receipt):
    with _LOCK:
        if str(_safe_path(path)) != receipt.get('path'):
            raise ValueError('恢复目标与记录不一致')
        before = _read(receipt['backup_path'])
        if _hash(before) != receipt['before_hash']:
            raise ValueError('备份已变化，无法恢复')
        if _hash(_read(path)) != receipt['after_hash']:
            raise ValueError('配置已有后续修改，不能覆盖恢复')
        _replace(path, before, receipt['after_hash'])
        return {'restored': True, 'hash': receipt['before_hash']}
