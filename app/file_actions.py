"""User-initiated file opening; never expose shell commands to the agent."""
import os
from pathlib import Path
import subprocess
from package_inventory import local
import psutil

OPENABLE = {'.txt','.md','.markdown','.json','.yaml','.yml','.toml','.ini','.log','.csv','.tsv',
            '.pdf','.doc','.docx','.xls','.xlsx','.ppt','.pptx','.odt','.ods','.rtf',
            '.png','.jpg','.jpeg','.gif','.webp','.bmp','.svg','.mp3','.wav','.mp4','.mkv','.mov'}

def dispatch(body):
    action=body.get('action')
    if action not in ('open','reveal'): return {'error':'不支持的文件操作'},400
    raw=body.get('path')
    if not isinstance(raw,str) or len(raw)>4096 or ':' in raw[2:]:
        return {'error':'文件路径无效'},400
    try:
        path=local(raw).resolve(strict=True)
        roots=[Path(p.mountpoint).resolve() for p in psutil.disk_partitions() if not p.mountpoint.startswith(('\\\\','//'))]
        if not path.is_file() or not any(path.is_relative_to(root) for root in roots):
            return {'error':'请选择本机文件'},400
        if action=='open':
            if path.suffix.lower() not in OPENABLE:
                return {'error':'此类型请在文件夹中打开或运行'},400
            os.startfile(str(path))
        else:
            subprocess.Popen([str(Path(os.environ.get('WINDIR','C:/Windows'))/'explorer.exe'),'/select,',str(path)])
        return {'ok':True},200
    except (OSError,ValueError):
        return {'error':'无法打开，请检查文件是否存在或已设置默认应用'},400
