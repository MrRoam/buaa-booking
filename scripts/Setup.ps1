param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$python = Join-Path $root '.venv\Scripts\python.exe'
if (Get-Command uv -ErrorAction SilentlyContinue) {
    if (-not (Test-Path -LiteralPath $python)) {
        uv venv --python '>=3.12' .venv
        if ($LASTEXITCODE -ne 0) { throw '无法创建 Python 环境，请安装 Python 3.12 或以上版本。' }
    }
    uv pip sync --python $python requirements.lock
} else {
    if (-not (Test-Path -LiteralPath $python)) {
        python -c 'import sys; assert sys.version_info >= (3,12), "Requires Python >=3.12"'
        if ($LASTEXITCODE -ne 0) { throw '请先安装 Python 3.12 或以上版本。' }
        python -m venv .venv
    }
    & $python -m pip install -r requirements.lock
}
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败。请检查网络或代理设置；证书校验保持开启。' }
& $python -m buaa_booking init
if ($LASTEXITCODE -ne 0) { throw '配置初始化失败。' }
Write-Host '安装完成。双击 启动.cmd，先查看余场或验证账号，再设置预约任务。'
