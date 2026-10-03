param()
$ErrorActionPreference = 'Stop'
$workbenchRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$pythonPath = Join-Path $workbenchRoot 'runtime/python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath = (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source }
$dataPath = Join-Path $workbenchRoot 'data'
if (-not (Test-Path -LiteralPath $dataPath)) { throw 'Workbench data directory does not exist.' }
$maintenanceLock = [IO.File]::Open((Join-Path $workbenchRoot 'maintenance.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
try {
$backupCode = @'
import os, sqlite3, sys, uuid
from datetime import datetime
from pathlib import Path
root = Path(sys.argv[1]).resolve()
source = root / 'data' / 'workbench.sqlite3'
directory = root / 'data' / 'backups'
for path in (source, directory):
    for part in (path, *path.parents):
        if part == root.parent: break
        if part.is_symlink() or part.is_junction(): raise SystemExit('Backup refuses linked workspace paths.')
if not source.is_file(): raise SystemExit('Workbench database does not exist.')
directory.mkdir(parents=True, exist_ok=True)
target = directory / ('workbench-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.sqlite3')
temporary = target.with_suffix('.tmp')
try:
    src = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=10)
    dst = sqlite3.connect(temporary)
    try:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchall() != [('ok',)]: raise RuntimeError('Backup integrity check failed.')
    finally:
        src.close()
        dst.close()
    os.replace(temporary, target)
    print(target)
finally:
    if temporary.exists(): temporary.unlink()
'@
$backupCode | & $pythonPath - $workbenchRoot
if ($LASTEXITCODE -ne 0) { throw 'Database backup failed; original database was not replaced.' }
} finally { $maintenanceLock.Dispose() }
