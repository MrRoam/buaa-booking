param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$env:PYTHONUTF8 = '1'
$python = Join-Path $root '.venv\Scripts\python.exe'
$dataPath = Join-Path $root 'data'
New-Item -ItemType Directory -Force -Path $dataPath | Out-Null
$log = Join-Path $dataPath ('daily-' + (Get-Date -Format 'yyyyMMdd') + '.log')
& $python -m buaa_booking --config (Join-Path $root 'config.json') run --scheduled --execute --watch --open-payment *> $log
exit $LASTEXITCODE
