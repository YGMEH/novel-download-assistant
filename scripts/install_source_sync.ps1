#Requires -Version 5.1
param(
    [string]$ProjectDir = "C:\novel\novel-download-assistant-main",
    [string]$PythonExe = "C:\Python312\python.exe",
    [string]$TaskName = "NovelSourceDailySync"
)

$ErrorActionPreference = "Stop"
$script = Join-Path $ProjectDir "scripts\sync_sources.py"
$logDir = Join-Path $ProjectDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
if (!(Test-Path $script)) { throw "找不到同步脚本: $script" }
if (!(Test-Path $PythonExe)) { throw "找不到 Python: $PythonExe" }

$logFile = Join-Path $logDir "source_sync.log"
$arguments = "/c `"`"$PythonExe`" `"$script`" --probe-key `"蛊真人`" >> `"$logFile`" 2>&1`"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $arguments -WorkingDirectory $ProjectDir
$trigger = New-ScheduledTaskTrigger -Daily -At 03:30
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -User "SYSTEM" -RunLevel Highest -Force | Out-Null

Write-Output "已安装计划任务: $TaskName"
Write-Output "执行时间: 每日 03:30"
Write-Output "脚本: $script"
Write-Output "手动测试: schtasks /Run /TN $TaskName"