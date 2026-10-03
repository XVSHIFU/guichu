param([ValidateRange(1024,65535)][int]$Port = 8765, [switch]$NoBrowser)
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
        if ($recordedProcess) {
            $command = (Get-CimInstance Win32_Process -Filter "ProcessId = $($record.process_id)").CommandLine
            $pattern = '(?i)(?:^|\s)"?' + [regex]::Escape($serverPath) + '"?(?=\s|$)'
            if ($record.server_path -ne $serverPath -or [string]$recordedProcess.StartTime.ToUniversalTime().Ticks -ne [string]$record.start_ticks -or $command -notmatch $pattern) { throw 'Process identity mismatch; no process was started or stopped. Check data/server-process.json.' }
            if ([int]$record.port -ne $Port) { throw "Workbench already uses port $($record.port); stop that instance first." }
            try { $health = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 3 } catch { throw 'Recorded workbench process is alive but unresponsive; inspect logs before retrying.' }
            if ($health.app -ne 'local-desk' -or [int]$health.pid -ne [int]$record.process_id -or $health.server_path -ne $serverPath) { throw 'Health response does not match the recorded workbench process.' }
            if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port" }
            Write-Output "Workbench already running: http://127.0.0.1:$Port"
            return
        }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $workbenchRoot 'dist/index.html'))) { throw 'Build the frontend first: npm install; npm run build.' }
    $probe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
    try { $probe.Start() } catch { throw "Port $Port is occupied; no existing process was stopped. Choose another port." } finally { $probe.Stop() }
    $pythonPath = (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    $arguments = '"' + $serverPath + '" --port ' + $Port
    $launched = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $workbenchRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $dataPath 'server.log') -RedirectStandardError (Join-Path $dataPath 'server-error.log')
    $launched.Refresh()
    $record = @{ process_id = $launched.Id; start_ticks = [string]$launched.StartTime.ToUniversalTime().Ticks; server_path = $serverPath; port = $Port }
    $record | ConvertTo-Json | Set-Content -LiteralPath $recordPath -Encoding UTF8
    $ready = $false
    for ($attempt = 0; $attempt -lt 50; $attempt++) {
        $launched.Refresh()
        if ($launched.HasExited) { throw 'Server exited; inspect data/server-error.log.' }
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 1
            if ($health.app -eq 'local-desk' -and [int]$health.pid -eq $launched.Id -and $health.server_path -eq $serverPath) { $ready = $true; break }
        } catch {}
        Start-Sleep -Milliseconds 200
    }
    if (-not $ready) { throw 'Server did not become ready. Process record retained; inspect logs before restarting.' }
    if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port" }
    Write-Output "Workbench started: http://127.0.0.1:$Port"
} finally { $maintenanceLock.Dispose() }
