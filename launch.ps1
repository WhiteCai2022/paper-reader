param([int]$Port = 8765, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$appRoot = $PSScriptRoot
$pythonPath = Join-Path $appRoot '.venv\Scripts\python.exe'
$stateDir = Join-Path $appRoot 'data'
$stateFile = Join-Path $stateDir 'server.json'

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Python environment missing. Run setup.ps1 first.'
}
if (-not (Test-Path -LiteralPath (Join-Path $appRoot 'frontend\dist\index.html'))) {
    throw 'Frontend build missing. Run setup.ps1 first.'
}
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null

function Read-LocalHealth([int]$targetPort) {
    $client = New-Object System.Net.WebClient
    $client.Proxy = $null
    try { return ($client.DownloadString("http://127.0.0.1:$targetPort/api/health") | ConvertFrom-Json) }
    catch { return $null }
    finally { $client.Dispose() }
}

if (Test-Path -LiteralPath $stateFile) {
    try {
        $previous = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
        $oldProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($previous.pid)" -ErrorAction SilentlyContinue
        if ($oldProcess -and $oldProcess.CommandLine -like '*backend.main:app*' -and $oldProcess.CommandLine.Contains($appRoot)) {
            if (Read-LocalHealth ([int]$previous.port)) {
                $url = "http://127.0.0.1:$($previous.port)"
                if (-not $NoBrowser) { Start-Process $url }
                Write-Output $url
                exit 0
            }
        }
    } catch { }
}

$selectedPort = $null
foreach ($candidatePort in $Port..($Port + 20)) {
    $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $candidatePort)
    try {
        $listener.Start()
        $selectedPort = $candidatePort
        break
    } catch { }
    finally { $listener.Stop() }
}
if ($null -eq $selectedPort) { throw 'No available local port in requested range.' }
$outLog = Join-Path $stateDir 'server.stdout.log'
$errLog = Join-Path $stateDir 'server.stderr.log'
$arguments = @('-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', "$selectedPort", '--app-dir', "`"$appRoot`"")
$process = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $appRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $outLog -RedirectStandardError $errLog
$url = "http://127.0.0.1:$selectedPort"
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    Start-Sleep -Milliseconds 300
    $process.Refresh()
    if ($process.HasExited) { throw "Server failed to start. See $errLog" }
    if (Read-LocalHealth $selectedPort) {
        @{ pid = $process.Id; port = $selectedPort; root = $appRoot; started_at = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding utf8
        if (-not $NoBrowser) { Start-Process $url }
        Write-Output $url
        exit 0
    }
}
Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
throw "Server startup timed out. See $errLog"
