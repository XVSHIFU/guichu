"""Elevate only the metadata scanner; results return over a one-use loopback socket.
The elevated process never opens the workbench database or writes scan results.
"""
import base64
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time

MAX_MESSAGE = 16 * 1024 * 1024


def _send(stream, value):
    stream.write(json.dumps(value, ensure_ascii=False).encode('utf-8') + b'\n')
    stream.flush()


def _read(stream):
    raw = stream.readline(MAX_MESSAGE + 1)
    if not raw or len(raw) > MAX_MESSAGE or not raw.endswith(b'\n'):
        raise ValueError('Invalid scanner message')
    return json.loads(raw)


def launch(connection, task, cancel):
    import directory_sizes as sizes
    listener = socket.socket()
    process = None
    try:
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        listener.settimeout(1)
        token = secrets.token_hex(32)
        config = {'port': listener.getsockname()[1], 'token': token, 'task': task}
        encoded = base64.b64encode(json.dumps(config).encode()).decode('ascii')
        # All command text is fixed; filesystem arguments are PowerShell literals.
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        args = subprocess.list2cmdline(['-I', str(Path(__file__).resolve()), encoded])
        command = '$ErrorActionPreference="Stop"; try { Start-Process -FilePath ' + quote(sys.executable) + ' -ArgumentList ' + quote(args) + ' -Verb RunAs -WindowStyle Hidden -Wait } catch { exit 1 }'
        process = subprocess.Popen(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        task.update(status='queued', error=None)
        sizes._persist(connection, task)
        deadline = time.monotonic() + 120
        while True:
            if cancel.is_set():
                task.update(status='cancelled'); return
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('管理员授权未完成或已取消，可重新尝试普通统计。')
            try:
                client, _ = listener.accept()
            except socket.timeout:
                continue
            client.settimeout(10)
            stream = client.makefile('rwb')
            try:
                if _read(stream) != {'token': token}:
                    stream.close(); client.close(); continue
                with client, stream:
                    _send(stream, {'cancel': cancel.is_set()})
                    while True:
                        updated = _read(stream)
                        if updated.get('id') != task['id'] or updated.get('path') != task['path']:
                            raise ValueError('扫描结果与请求不一致')
                        task.update(updated)
                        sizes._persist(connection, task)
                        _send(stream, {'cancel': cancel.is_set()})
                        if task['status'] in sizes.TERMINAL:
                            return
            finally:
                stream.close(); client.close()
    except Exception as error:
        task.update(status='cancelled' if cancel.is_set() else 'failed', error=str(error) or '管理员统计未完成')
    finally:
        listener.close()
        sizes._persist(connection, task)
        with sizes.LOCK:
            sizes.ACTIVE.pop(task['id'], None)


def main(encoded):
    import ctypes
    import directory_sizes as sizes
    if os.name != 'nt' or not ctypes.windll.shell32.IsUserAnAdmin():
        raise RuntimeError('Administrator token required')
    config = json.loads(base64.b64decode(encoded))
    task = config['task']
    cancel = threading.Event()
    with socket.create_connection(('127.0.0.1', int(config['port'])), timeout=10) as client, client.makefile('rwb') as stream:
        _send(stream, {'token': config['token']})
        if _read(stream)['cancel']: return
        def persist(connection, value):
            value['updated_at'] = sizes._now()
            _send(stream, value)
            if _read(stream)['cancel']: cancel.set()
        sizes._persist = persist
        try:
            sizes._validate(task['path'])
            sizes._worker(None, task, cancel)
        except Exception:
            task.update(status='failed', error='管理员扫描未完成，目录可能不可用。')
            persist(None, task)


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main(sys.argv[1])
