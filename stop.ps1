$ErrorActionPreference = 'Stop'
$stateFile = Join-Path $PSScriptRoot 'data\server.json'
if (-not (Test-Path -LiteralPath $stateFile)) { Write-Output 'No saved server process.'; exit 0 }
$state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
$ownedProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($state.pid)" -ErrorAction SilentlyContinue
if ($ownedProcess) {
    if ($ownedProcess.CommandLine -notlike '*backend.main:app*' -or -not $ownedProcess.CommandLine.Contains($PSScriptRoot)) {
        throw 'Saved process identity does not match this reader; no process was stopped.'
    }
    Stop-Process -Id $state.pid
    Write-Output 'Paper reader stopped.'
} else { Write-Output 'Paper reader is already stopped.' }
Remove-Item -LiteralPath $stateFile
