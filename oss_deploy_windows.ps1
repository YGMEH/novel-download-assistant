#Requires -Version 5.1
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [ValidateSet('Install', 'Worker')]
    [string]$Mode = 'Install',
    [string]$ProjectDir = 'C:\novel\novel-download-assistant-main',
    [Parameter(Mandatory=$false)][string]$PackageUrl = '',
    [string]$PythonExe = 'C:\Python312\python.exe',
    [string]$TaskName = 'NovelOssDeploy',
    [int]$Port = 8765
)
$ErrorActionPreference = 'Stop';$ProgressPreference='SilentlyContinue'
$LogDir=Join-Path $ProjectDir 'logs';$Log=Join-Path $LogDir 'oss_deploy.log';$State=Join-Path $ProjectDir '.oss-deploy-state.json'
New-Item -ItemType Directory -Force -Path $ProjectDir,$LogDir | Out-Null
function Write-Log([string]$m){Add-Content -LiteralPath $Log -Value "$(Get-Date -Format s) $m" -Encoding UTF8}
function Install-Task {
  if(-not $PackageUrl){throw '安装时必须提供 OSS latest.zip 的公开 HTTPS 地址'}
  $args='-NoProfile -ExecutionPolicy Bypass -File "'+$PSCommandPath+'" -Mode Worker -ProjectDir "'+$ProjectDir+'" -PackageUrl "'+$PackageUrl+'" -PythonExe "'+$PythonExe+'" -TaskName "'+$TaskName+'" -Port '+$Port
  $action=New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument $args -WorkingDirectory $ProjectDir
  $trigger=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
  $settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -User SYSTEM -RunLevel Highest -Force | Out-Null
  Write-Log "installed task=$TaskName";schtasks.exe /Run /TN $TaskName | Out-Null
  Write-Host "OSS 自动部署已安装：$TaskName，每5分钟检查一次。"
}
function Stop-App {Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {$_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -like "*$ProjectDir*server.py*"} | ForEach-Object {Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}}
function Worker {
  $tmp=Join-Path $env:TEMP 'novel-package-latest.zip';$extract=Join-Path $env:TEMP 'novel-package-latest';$backup=Join-Path $ProjectDir ('backups\oss_'+(Get-Date -Format yyyyMMdd_HHmmss))
  try {
    Invoke-WebRequest -UseBasicParsing -Uri $PackageUrl -OutFile $tmp -TimeoutSec 120
    if((Get-Item $tmp).Length -lt 10000){throw 'OSS 部署包过小'}
    $hash=(Get-FileHash $tmp -Algorithm SHA256).Hash
    if(Test-Path $State){try{if(([string](Get-Content $State -Raw|ConvertFrom-Json).sha)-eq $hash){Write-Log "unchanged sha=$hash";return}}catch{}}
    New-Item -ItemType Directory -Force -Path $backup | Out-Null
    foreach($f in @('rule_engine.py','source_manager.py','server.py','downloader.py','index.html','requirements.txt','config.json','sources','scripts')){ $p=Join-Path $ProjectDir $f;if(Test-Path $p){$d=Join-Path $backup $f;New-Item -ItemType Directory -Force -Path (Split-Path $d) -ErrorAction SilentlyContinue|Out-Null;Copy-Item $p $d -Recurse -Force}}
    Remove-Item $extract -Recurse -Force -ErrorAction SilentlyContinue;Expand-Archive -Path $tmp -DestinationPath $extract -Force
    foreach($f in @('rule_engine.py','source_manager.py','server.py','downloader.py','index.html','requirements.txt','config.json','sources','scripts')){ $s=Join-Path $extract $f;$d=Join-Path $ProjectDir $f;if(Test-Path $s){Copy-Item $s $d -Recurse -Force}}
    & $PythonExe -m py_compile (Join-Path $ProjectDir 'rule_engine.py') (Join-Path $ProjectDir 'source_manager.py') (Join-Path $ProjectDir 'server.py') (Join-Path $ProjectDir 'scripts\sync_sources.py');if($LASTEXITCODE -ne 0){throw 'Python 语法校验失败'}
    & $PythonExe (Join-Path $ProjectDir 'scripts\sync_sources.py') --probe-key '蛊真人' >> $Log 2>&1;$sync=$LASTEXITCODE
    Stop-App;Start-Process -FilePath $PythonExe -WorkingDirectory $ProjectDir -ArgumentList "-u server.py --host 0.0.0.0 --port $Port" -RedirectStandardOutput (Join-Path $LogDir 'server.log') -RedirectStandardError (Join-Path $LogDir 'server-error.log') -WindowStyle Hidden|Out-Null;Start-Sleep 3
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 -Uri "http://127.0.0.1:$Port/api/sources"|Out-Null
    @{sha=$hash;deployed_at=(Get-Date).ToString('s');sync_exit=$sync}|ConvertTo-Json|Set-Content $State -Encoding UTF8;Write-Log "deployed sha=$hash sync_exit=$sync"
  } catch {Write-Log "FAILED error=$($_.Exception.Message)";if(Test-Path $backup){foreach($f in @('rule_engine.py','source_manager.py','server.py','downloader.py','index.html','requirements.txt','config.json','sources','scripts')){$s=Join-Path $backup $f;$d=Join-Path $ProjectDir $f;if(Test-Path $s){Copy-Item $s $d -Recurse -Force}}};exit 1} finally {Remove-Item $tmp -Force -ErrorAction SilentlyContinue;Remove-Item $extract -Recurse -Force -ErrorAction SilentlyContinue}
}
if($Mode -eq 'Install'){Install-Task}else{Worker}