param([Parameter(Mandatory=$true)][ValidateSet('export','import')][string]$Action, [string]$ArchivePath, [ValidateRange(1024,65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
if (-not $ArchivePath) {
    Add-Type -AssemblyName System.Windows.Forms
    if ($Action -eq 'export') {
        $dialog = New-Object System.Windows.Forms.SaveFileDialog
        $dialog.FileName = 'guichu-workspace-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.zip'
    } else {
        $dialog = New-Object System.Windows.Forms.OpenFileDialog
    }
    $dialog.Filter = 'Guichu workspace (*.zip)|*.zip'
    if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { return }
    $ArchivePath = $dialog.FileName
    if ($Action -eq 'import') {
        $answer = [System.Windows.Forms.MessageBox]::Show('Restore this workspace? Current data will be preserved in a separate folder. Model credentials must be configured again.', 'Guichu', 'YesNo', 'Question')
        if ($answer -ne 'Yes') { return }
    }
}
$workbenchRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$serverPath = Join-Path $workbenchRoot 'server.py'
$dataPath = Join-Path $workbenchRoot 'data'
$recordPath = Join-Path $dataPath 'server-process.json'
New-Item -ItemType Directory -Force -Path $dataPath | Out-Null
$maintenanceLock = [IO.File]::Open((Join-Path $workbenchRoot 'maintenance.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
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
    $pythonPath = Join-Path $workbenchRoot 'runtime/python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath = (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source }
    & $pythonPath (Join-Path $workbenchRoot "workspace_transfer.py") $Action ([IO.Path]::GetFullPath($ArchivePath))
    if ($LASTEXITCODE -ne 0) { throw "Workspace transfer failed; inspect the message above." }
} finally { $maintenanceLock.Dispose() }
