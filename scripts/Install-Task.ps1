param([switch]$Enable, [switch]$Update, [string]$TaskName = 'BUAA-Badminton-Booking')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$configPath = Join-Path $root 'config.json'
$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$python = Join-Path $root '.venv\Scripts\python.exe'
& $python -m buaa_booking --config $configPath plan
if ($LASTEXITCODE -ne 0) { throw '配置校验失败，未安装任务。' }
$start = [datetime]::Today.Add([TimeSpan]::Parse($config.release_time)).AddMinutes(-5)
Write-Host ('任务名：' + $TaskName)
Write-Host ('每天北京时间 ' + $start.ToString('HH:mm:ss') + ' 启动；进程在放场时刻提交。')
Write-Host '需要 Windows 时区为北京时间，并保持该 Windows 账户已登录。锁屏可以；关机不能运行。'
if (-not $Enable) {
    Write-Host '当前只预览，未创建任务。确定日期、时段并完成 check 后，添加 -Enable 才会安装。'
    exit 0
}
if (-not $config.enabled) { throw '自动预约仍为关闭状态。先在 config.json 设置日期、时段和 enabled=true。' }
if ((Get-TimeZone).BaseUtcOffset.TotalHours -ne 8) { throw 'Windows 时区不是 UTC+8，未安装任务。' }
$preflightPath = Join-Path $root 'data\preflight.json'
if (-not (Test-Path -LiteralPath $preflightPath)) { throw '请先运行 check 验证真实登录和预约资料。' }
$preflight = Get-Content -LiteralPath $preflightPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $preflight.ready -or $preflight.venue_site_id -ne $config.venue_site_id) { throw '最近一次预约资料检查未通过，请先运行 check。' }
if (([DateTimeOffset]::Now - [DateTimeOffset]::Parse($preflight.checked_at)).TotalHours -gt 24) { throw '最近验证已超过 24 小时，请重新运行 check。' }
$scriptPath = Join-Path $PSScriptRoot 'Run-Daily.ps1'
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    $owned = @($existing.Actions).Count -eq 1 -and $existing.Actions[0].WorkingDirectory -eq $root -and $existing.Actions[0].Arguments.Contains('"' + $scriptPath + '"')
    if (-not $Update -or -not $owned) { throw '同名任务已存在且未允许更新，或属于其他目录；未覆盖该任务。' }
}
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $scriptPath + '"'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At $start
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description '北航主馆预约；仅创建待支付订单，付款由本人完成。' -Force:$Update | Out-Null
Write-Host '任务已安装；尚未手动启动。请验证电脑的睡眠唤醒功能。'
