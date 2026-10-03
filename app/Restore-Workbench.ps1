param([Parameter(Mandatory=$true)][string]$BackupPath, [ValidateRange(1024,65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$workbenchRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$serverPath = Join-Path $workbenchRoot 'server.py'
$dataPath = Join-Path $workbenchRoot 'data'
$recordPath = Join-Path $dataPath 'server-process.json'
New-Item -ItemType Directory -Force -Path $dataPath | Out-Null
$maintenanceLock = [IO.File]::Open((Join-Path $dataPath 'maintenance.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
try {
    if (Test-Path -LiteralPath $recordPath) {
        $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
        $recordedProcess = Get-Process -Id $record.process_id -ErrorAction SilentlyContinue
        if ($recordedProcess -and [string]$recordedProcess.StartTime.ToUniversalTime().Ticks -eq [string]$record.start_ticks) { throw 'Workbench process is still running. Stop it before restoring; restore never force-stops processes.' }
    }
    $pattern = '(?i)(?:^|\s)"?' + [regex]::Escape($serverPath) + '"?(?=\s|$)'
    $matching = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match $pattern }
    if ($matching) { throw 'This workbench server is still running; stop it before restoring.' }
    try { $health = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 2 } catch { $health = $null }
    if ($health.app -eq 'local-desk') { throw 'A workbench service still responds on this port; confirm it is stopped.' }
    $pythonPath = (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    $restoreCode = @'
import os, sqlite3, sys, uuid
from datetime import datetime
from pathlib import Path
root = Path(sys.argv[1]).resolve()
directory = root / 'data' / 'backups'
target = root / 'data' / 'workbench.sqlite3'
source = Path(sys.argv[2]).absolute()
if not source.is_relative_to(directory) or source.suffix != '.sqlite3': raise SystemExit('Restore source must be a .sqlite3 backup inside this workspace data/backups.')
for path in (source, target, directory):
    for part in (path, *path.parents):
        if part == root.parent: break
        if part.is_symlink() or part.is_junction(): raise SystemExit('Restore refuses linked workspace paths.')
if not source.resolve().is_relative_to(directory.resolve()): raise SystemExit('Backup escapes workspace.')
if not source.is_file(): raise SystemExit('Backup does not exist.')
def snapshot(src_path, dst_path):
    src = sqlite3.connect(src_path.as_uri() + '?mode=ro', uri=True, timeout=10)
    dst = sqlite3.connect(dst_path)
    try:
        if src.execute('PRAGMA integrity_check').fetchall() != [('ok',)]: raise RuntimeError('Source integrity check failed.')
        tables = {row[0] for row in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'scans', 'notes', 'changes'}.issubset(tables): raise RuntimeError('Not a workbench database backup.')
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchall() != [('ok',)]: raise RuntimeError('Copied database integrity check failed.')
    finally:
        src.close()
        dst.close()
temporary = target.parent / ('restore-' + uuid.uuid4().hex + '.tmp')
try:
    snapshot(source, temporary)
    if target.exists():
        current_backup = directory / ('before-restore-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.sqlite3')
        snapshot(target, current_backup)
        print('Current database backup: ' + str(current_backup))
        # A read-only backup of a WAL database may leave SQLite-owned sidecars.
        # Let SQLite checkpoint and close them; never remove them ourselves.
        current = sqlite3.connect(target, timeout=2)
        try:
            if current.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] != 0:
                raise RuntimeError('Database is busy; checkpoint refused.')
            if current.execute('PRAGMA journal_mode=DELETE').fetchone()[0].lower() != 'delete':
                raise RuntimeError('Database is busy; journal transition refused.')
        finally:
            current.close()
    if any(Path(str(target) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise RuntimeError('SQLite recovery sidecars remain; restore refused without deleting them.')
    os.replace(temporary, target)
    print('Restored: ' + str(target))
finally:
    if temporary.exists(): temporary.unlink()
'@
    $restoreCode | & $pythonPath - $workbenchRoot ([IO.Path]::GetFullPath($BackupPath))
    if ($LASTEXITCODE -ne 0) { throw 'Database restore failed; original database was not actively deleted.' }
} finally { $maintenanceLock.Dispose() }
