param([ValidateRange(1024,65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$workbenchRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$serverPath = Join-Path $workbenchRoot 'server.py'
$dataPath = Join-Path $workbenchRoot 'data'
$recordPath = Join-Path $dataPath 'server-process.json'
if (-not (Test-Path -LiteralPath $recordPath)) { throw 'No workbench process record; refusing to stop processes by port or name.' }
$maintenanceLock = [IO.File]::Open((Join-Path $dataPath 'maintenance.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
try {
    $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
    if ($record.server_path -ne $serverPath -or [int]$record.port -ne $Port) { throw 'Workbench path or port does not match the process record.' }
    $recordedProcess = Get-Process -Id $record.process_id -ErrorAction SilentlyContinue
    if (-not $recordedProcess) { Write-Output 'Recorded workbench process has already stopped.'; return }
    $command = (Get-CimInstance Win32_Process -Filter "ProcessId = $($record.process_id)").CommandLine
    $pattern = '(?i)(?:^|\s)"?' + [regex]::Escape($serverPath) + '"?(?=\s|$)'
    if ([string]$recordedProcess.StartTime.ToUniversalTime().Ticks -ne [string]$record.start_ticks -or $command -notmatch $pattern) { throw 'PID, start time or program path mismatch; no process was stopped.' }
    try { $health = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 3 } catch { throw 'Cannot verify activity; refusing to force-stop a potentially writing process.' }
    if ($health.app -ne 'local-desk' -or [int]$health.pid -ne [int]$record.process_id -or $health.server_path -ne $serverPath) { throw 'Health response does not match the workbench process identity.' }
    if ($null -eq $health.busy) { throw 'Server has no activity status; safe stop requires the maintenance API.' }
    if ($health.busy) { throw ('Workbench has active tasks; stop refused: ' + ($health.busy_reasons -join '; ')) }
    $state = Invoke-RestMethod "http://127.0.0.1:$Port/api/state" -TimeoutSec 3
    $headers = @{ Origin = "http://127.0.0.1:$Port"; 'X-Desk-Token' = $state.token }
    try { $null = Invoke-RestMethod "http://127.0.0.1:$Port/api/shutdown" -Method Post -Headers $headers -ContentType 'application/json' -Body '{}' -TimeoutSec 5 } catch { throw 'Server refused shutdown or became busy; no process was force-stopped. Check tasks and retry.' }
    if (-not $recordedProcess.WaitForExit(10000)) { throw 'Server has not exited yet; no process was force-stopped. Check tasks and logs.' }
    Write-Output 'Workbench stopped safely.'
} finally { $maintenanceLock.Dispose() }
