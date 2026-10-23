param([string]$Python = '', [string]$Pnpm = '')
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$tempPath = Join-Path $root 'tmp'
New-Item -ItemType Directory -Path $tempPath -Force | Out-Null
$env:TEMP = $tempPath
$env:TMP = $tempPath
if (-not $Python) {
    $bundled = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $bundled) { $Python = $bundled }
    else { $Python = (Get-Command python -ErrorAction Stop).Source }
}
if (-not $Pnpm) { $Pnpm = (Get-Command pnpm -ErrorAction Stop).Source }
& $Python -m venv (Join-Path $root '.venv')
if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
$localPython = Join-Path $root '.venv\Scripts\python.exe'
& $localPython -m pip install -r (Join-Path $root 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
Push-Location (Join-Path $root 'frontend')
try {
    & $Pnpm --store-dir (Join-Path $root 'frontend\.pnpm-store') install --frozen-lockfile --config.node-linker=hoisted
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    & $Pnpm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
Write-Output 'Setup complete. Run launch.ps1 to start the reader.'
