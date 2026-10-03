"""Only launch the system MSI UI for a revalidated scanned product GUID.

Never reads UninstallString and never requests silent uninstall or elevation.
Reference: https://learn.microsoft.com/en-us/windows/win32/msi/command-line-options
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

try:
    import winreg
except ImportError:
    winreg = None

GUID = re.compile(r'\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}')
UNINSTALL = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'


def _identity(obj):
    if not isinstance(obj, dict) or obj.get('kind') != 'software' or obj.get('windowsInstaller') is not True:
        raise ValueError('仅支持明确登记为 Windows Installer 的软件')
    if obj.get('registryHive') not in {'HKLM', 'HKCU'} or type(obj.get('registryView')) is not int or obj['registryView'] not in {256, 512}:
        raise ValueError('缺少可信软件注册来源')
    if not isinstance(obj.get('registryKey'), str) or not GUID.fullmatch(obj['registryKey']):
        raise ValueError('仅支持 GUID 产品代码的 MSI 登记')
    if not isinstance(obj.get('name'), str) or not obj['name']:
        raise ValueError('软件名称无效')
    return obj['registryHive'], obj['registryView'], obj['registryKey']


def _registered(obj):
    hive, view, child = _identity(obj)
    if winreg is None:
        raise OSError('仅 Windows 支持此操作')
    root = winreg.HKEY_LOCAL_MACHINE if hive == 'HKLM' else winreg.HKEY_CURRENT_USER
    try:
        handle = winreg.OpenKey(root, UNINSTALL + '\\' + child, 0, winreg.KEY_READ | view)
    except FileNotFoundError:
        return None
    with handle as key:
        name = winreg.QueryValueEx(key, 'DisplayName')[0]
        installer = winreg.QueryValueEx(key, 'WindowsInstaller')[0]
        if name != obj['name'] or type(installer) is not int or installer != 1:
            raise ValueError('软件注册身份已变化')
        try:
            version = str(winreg.QueryValueEx(key, 'DisplayVersion')[0])
        except FileNotFoundError:
            version = ''
    return dict(name=name, version=version, registryHive=hive, registryView=view, registryKey=child, product_code=child)


def _installer_path():
    if os.name != 'nt':
        raise OSError('仅 Windows 支持此操作')
    function = ctypes.WinDLL('kernel32', use_last_error=True).GetWindowsDirectoryW
    function.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    function.restype = ctypes.c_uint
    buffer = ctypes.create_unicode_buffer(32768)
    length = function(buffer, len(buffer))
    if not 0 < length < len(buffer):
        raise OSError('无法定位系统目录')
    path = Path(buffer.value) / 'System32' / 'msiexec.exe'
    if not path.is_absolute() or not path.is_file() or str(path).startswith(('\\\\', '//')):
        raise OSError('系统安装器不可用')
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError('系统安装器路径不能包含链接')
    return str(path)


def preview(obj):
    registered = _registered(obj)
    if registered is None:
        raise ValueError('软件登记已不存在，请重新扫描')
    fingerprint = hashlib.sha256(json.dumps(registered, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {**registered, 'fingerprint': fingerprint, 'installer_path': _installer_path(),
            'usage_check': 'installer', 'usage_note': '文件占用由 Windows Installer 在系统窗口检查；本机清单不证明软件已关闭，请先关闭相关程序。',
            'scope': '仅打开 Windows Installer 交互卸载入口，由你在系统窗口继续操作。',
            'recovery_limit': '工作台不能自动恢复已卸载的软件；如需恢复请重新安装。'}


def apply(obj, expected_fingerprint):
    summary = preview(obj)
    if summary['fingerprint'] != expected_fingerprint:
        raise ValueError('软件登记在预览后已变化')
    process = subprocess.Popen([summary['installer_path'], '/x', summary['product_code']],
                               shell=False, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return dict(state='waiting_user', pid=process.pid, product_code=summary['product_code'],
                message='已打开官方卸载入口；尚未确认卸载结果，请完成系统窗口后重新核验。')


def verify(obj):
    registered = _registered(obj)
    return dict(state='removed' if registered is None else 'still_registered',
                message='原软件登记已移除；此结果不保证所有文件都已清除。' if registered is None else '软件仍有登记；可能尚未完成、已取消或卸载未成功。')
