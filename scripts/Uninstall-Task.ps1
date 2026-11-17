param([string]$TaskName = 'BUAA-Badminton-Booking')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    $root = Split-Path -Parent $PSScriptRoot
    $scriptPath = Join-Path $PSScriptRoot 'Run-Daily.ps1'
    if (@($task.Actions).Count -ne 1 -or $task.Actions[0].WorkingDirectory -ne $root -or -not $task.Actions[0].Arguments.Contains('"' + $scriptPath + '"')) { throw '同名任务属于其他目录，未移除。' }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host '已移除定时任务。不会取消已经创建的场地订单。'
} else { Write-Host '未找到该任务。' }
