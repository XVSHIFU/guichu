"""Restricted Windows directory recycling, never a permanent-delete fallback.

Server callers must bind paths/protected roots to an explicit confirmed proposal,
persist an executing journal before apply, and require a user acknowledgement
that related programs are closed when usage_check is partial. Process exe/cwd
checks cannot prove absence of open handles. Metadata revalidation is not atomic
against external writers. Recovery is manual in Windows Recycle Bin.

Microsoft contract: ITransferSource.RecycleItem recycles into the supplied
Recycle Bin and returns the new item. The distinct RemoveItem operation is never
called. No generic DeleteItem/SHFileOperation or Send2Trash fallback is used.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import threading
import time

import psutil

MAX_ENTRIES = 50000
MAX_SECONDS = 10
LOCK = threading.Lock()
RESTORE_NOTE = '可在 Windows 回收站手动恢复；本工具不提供自动恢复，回收站被清空后无法通过本工具恢复。'


def _is_link(path, metadata=None):
    info = metadata or path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _overlaps(left, right):
    return left.is_relative_to(right) or right.is_relative_to(left)


def _validate(path, protected_paths):
    if not isinstance(path, (str, os.PathLike)):
        raise ValueError('请选择明确的本机目录')
    raw = str(path)
    candidate = Path(path)
    if not candidate.is_absolute() or raw.startswith(('\\\\', '//')):
        raise ValueError('不支持相对路径、网络或设备路径')
    try:
        if any(_is_link(part) for part in (candidate, *candidate.parents)):
            raise ValueError('不回收链接目录或含链接祖先的路径')
        candidate = candidate.resolve(strict=True)
        if candidate == Path(candidate.anchor) or not stat.S_ISDIR(candidate.stat().st_mode):
            raise ValueError('不能回收磁盘根或非普通目录')
        home = Path.home().resolve()
        if home.is_relative_to(candidate):
            raise ValueError('不能回收用户根目录或其祖先')
        system_drive = os.environ.get('SystemDrive', 'C:')
        system_roots = [os.environ.get('SystemRoot', system_drive + '/Windows'),
                        os.environ.get('ProgramFiles', system_drive + '/Program Files'),
                        os.environ.get('ProgramFiles(x86)', system_drive + '/Program Files (x86)'),
                        os.environ.get('ProgramData', system_drive + '/ProgramData')]
        for protected in [*system_roots, *protected_paths]:
            root = Path(protected).resolve()
            if _overlaps(candidate, root):
                raise ValueError('此位置位于受保护目录内或包含受保护目录')
        if Path.cwd().resolve().is_relative_to(candidate) or Path(sys.executable).resolve().is_relative_to(candidate):
            raise ValueError('工作台正在使用此目录')
        if os.name == 'nt':
            import ctypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
            kernel.GetDriveTypeW.restype = ctypes.c_uint
            if kernel.GetDriveTypeW(candidate.anchor) != 3:
                raise ValueError('首版仅支持本机固定磁盘的回收站')
        return candidate
    except OSError as exc:
        raise ValueError('目录无法完整核验，未执行回收') from exc


def _manifest(root):
    started = time.monotonic()
    stack = [root]
    records = []
    files = directories = size = 0
    def record(path, info):
        nonlocal files, directories, size
        if time.monotonic() - started >= MAX_SECONDS or len(records) >= MAX_ENTRIES:
            raise ValueError('目录超过预览时间或条目上限，未执行回收')
        if _is_link(path, info):
            raise ValueError('目录内存在链接或重解析项，未执行回收')
        if stat.S_ISDIR(info.st_mode):
            kind = 'directory'
            directories += 1
        elif stat.S_ISREG(info.st_mode):
            kind = 'file'
            files += 1
            size += info.st_size
        else:
            raise ValueError('目录内存在非普通文件，未执行回收')
        records.append((str(path.relative_to(root)), kind, info.st_size,
                        info.st_mtime_ns, info.st_dev, info.st_ino))
    try:
        record(root, root.lstat())
        while stack:
            directory = stack.pop()
            if _is_link(directory):
                raise ValueError('预览期间目录变为链接，未执行回收')
            with os.scandir(directory) as entries:
                for entry in entries:
                    child = Path(entry.path)
                    info = os.stat(child, follow_symlinks=False)
                    record(child, info)
                    if stat.S_ISDIR(info.st_mode):
                        stack.append(child)
        fingerprint = hashlib.sha256(json.dumps([str(root), sorted(records)], ensure_ascii=False,
                                                separators=(',', ':')).encode()).hexdigest()
        return {'fingerprint': fingerprint, 'files': files, 'directories': directories, 'bytes': size}
    except OSError as exc:
        raise ValueError('目录权限或内容已变化，无法完整预览；未执行回收') from exc


def _usage(root):
    partial = False
    matches = []
    try:
        for process in psutil.process_iter():
            matched = []
            for field in ('exe', 'cwd'):
                try:
                    raw = getattr(process, field)()
                    if raw and Path(raw).resolve().is_relative_to(root):
                        matched.append(field)
                except (psutil.NoSuchProcess, psutil.ZombieProcess):
                    continue
                except (psutil.AccessDenied, OSError):
                    partial = True
            if matched:
                matches.append({'pid': process.pid, 'matched': matched})
    except (psutil.Error, OSError):
        partial = True
    if matches:
        error = ValueError('检测到进程正在使用此目录，请关闭相关程序后重新预览')
        error.processes = matches
        raise error
    return {'processes': [], 'usage_check': 'partial' if partial else 'complete'}


def preview(path, protected_paths=()):
    root = _validate(path, protected_paths)
    return {'path': str(root), **_manifest(root), **_usage(root), 'restore_note': RESTORE_NOTE}


def _recycle(path):
    if os.name != 'nt':
        raise ValueError('回收仅支持 Windows，不提供永久删除替代')
    try:
        import pythoncom
        from win32com.shell import shell
    except ImportError as exc:
        raise ValueError('缺少 Windows 回收接口依赖，未执行回收') from exc
    pythoncom.CoInitialize()
    parent = item = destination = transfer = recycled = None
    try:
        parent = shell.SHCreateItemFromParsingName(str(Path(path).parent), None, shell.IID_IShellItem)
        item = shell.SHCreateItemFromParsingName(str(path), None, shell.IID_IShellItem)
        destination = shell.SHCreateItemFromParsingName('shell:RecycleBinFolder', None, shell.IID_IShellItem)
        transfer = parent.BindToHandler(None, shell.BHID_Transfer, shell.IID_ITransferSource)
        # The dedicated RecycleItem contract has no permanent-delete fallback;
        # RemoveItem is a separate method and is deliberately never used here.
        result, recycled = transfer.RecycleItem(item, destination, 0)
        if result < 0 or result & 0x80000000 or recycled is None:
            raise ValueError('Windows 未确认回收结果')
        return True
    except Exception as exc:
        raise ValueError('Windows 回收操作失败或未获回收确认，不会尝试永久删除') from exc
    finally:
        parent = item = destination = transfer = recycled = None
        pythoncom.CoUninitialize()


def apply(path, expected_fingerprint, protected_paths=()):
    with LOCK:
        current = preview(path, protected_paths)
        if current['fingerprint'] != expected_fingerprint:
            raise ValueError('目录内容已变化，请重新预览并确认')
        root = Path(current['path'])
        try:
            success = _recycle(root)
            if success is not True or os.path.lexists(root):
                raise ValueError('目标仍存在或回收结果未确认，请检查执行结果')
        except Exception as exc:
            error = ValueError('回收未确认完成，请检查目录与 Windows 回收站；不会重试永久删除')
            error.receipt = {'state': 'failed' if os.path.lexists(root) else 'uncertain',
                             'path': str(root), 'restore_note': RESTORE_NOTE}
            raise error from exc
        return {**current, 'state': 'recycled', 'api': 'ITransferSource.RecycleItem',
                'completed_at': datetime.now(timezone.utc).isoformat()}
