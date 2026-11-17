param()
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$config = Get-Content -LiteralPath (Join-Path $root 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($config.enabled) { Write-Output '配置：自动预约已开启。' } else { Write-Output '配置：自动预约关闭。' }
$task = Get-ScheduledTask -TaskName 'BUAA-Badminton-Booking' -ErrorAction SilentlyContinue
if (-not $task) { Write-Output 'Windows 定时任务：未安装。设置日期和时段后，点击“启用定时抢场”。'; exit 0 }
$scriptPath = Join-Path $PSScriptRoot 'Run-Daily.ps1'
if (@($task.Actions).Count -ne 1 -or $task.Actions[0].WorkingDirectory -ne $root -or -not $task.Actions[0].Arguments.Contains('"' + $scriptPath + '"')) {
    Write-Output 'Windows 定时任务：同名任务属于其他目录，本工具不会修改它。'
    exit 0
}
$info = Get-ScheduledTaskInfo -TaskName $task.TaskName
Write-Output ('Windows 定时任务：' + $task.State)
Write-Output ('下次启动：' + $info.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss'))
Write-Output '每天 06:55 启动，仅在对应已设置的打球日期时，等待至 07:00 抢场。'
Write-Output ('运行目录：' + $root)
