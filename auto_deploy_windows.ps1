#Requires -Version 5.1
[CmdletBinding()]
param(
  [ValidateSet('Install','Worker')][string]$Mode='Install',
  [string]$ProjectDir='',[string]$PythonExe='',
  [string]$TaskName='NovelAutoDeploy',[string]$Repo='YGMEH/novel-download-assistant',[int]$Port=8765
)
$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue'
function Resolve-Project([string]$Requested) {
  if($Requested){return [IO.Path]::GetFullPath($Requested)}
  foreach($p in @('C:\Users\Administrator\Downloads\novel_oss','C:\novel\novel-download-assistant-main','C:\novel-download-assistant',(Split-Path -Parent $PSCommandPath))){if(Test-Path (Join-Path $p 'server.py')){return $p}}
  throw 'ProjectDir was not supplied and no installation containing server.py was found.'
}
$ProjectDir=Resolve-Project $ProjectDir
if(-not $PythonExe){$v=Join-Path $ProjectDir '.venv\Scripts\python.exe';if(Test-Path $v){$PythonExe=$v}elseif(Test-Path 'C:\Python312\python.exe'){$PythonExe='C:\Python312\python.exe'}else{throw 'Python was not found.'}}
$LogDir=Join-Path $ProjectDir 'logs';$LogFile=Join-Path $LogDir 'auto_deploy.log';$State=Join-Path $ProjectDir '.auto-deploy-state.json';$LockFile=Join-Path $ProjectDir '.auto-deploy.lock';$PidFile=Join-Path $ProjectDir '.server.pid'
$Files=@('rule_engine.py','source_manager.py','server.py','downloader.py','tomato_source.py','index.html','requirements.txt','scripts/sync_sources.py')
$Apis=@("https://api.github.com/repos/$Repo/commits/main","https://ghfast.top/https://api.github.com/repos/$Repo/commits/main")
$Bases=@("https://raw.githubusercontent.com/$Repo","https://cdn.jsdelivr.net/gh/$Repo","https://ghfast.top/https://raw.githubusercontent.com/$Repo")
New-Item -ItemType Directory -Force -Path $ProjectDir,$LogDir|Out-Null
function Log([string]$m){$line="$(Get-Date -Format s) $m";Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8;if($Mode -eq 'Install'){Write-Host $line}}
function Assert-Admin{$id=[Security.Principal.WindowsIdentity]::GetCurrent();$p=New-Object Security.Principal.WindowsPrincipal($id);if(-not $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Run Install mode as Administrator.'}}
function Remote-Sha{$h=@{'User-Agent'='NovelAutoDeploy/2.1';Accept='application/vnd.github+json'};foreach($u in $Apis){try{$r=Invoke-RestMethod -UseBasicParsing -Uri $u -Headers $h -TimeoutSec 20;if($r.sha -match '^[0-9a-f]{40}$'){return [string]$r.sha}}catch{Log "sha endpoint failed url=$u error=$($_.Exception.Message)"}};throw 'All GitHub commit endpoints failed.'}
function Stop-App{
  if(Test-Path $PidFile){try{Stop-Process -Id ([int](Get-Content $PidFile -Raw)) -Force -ErrorAction Stop}catch{};Remove-Item $PidFile -Force -ErrorAction SilentlyContinue}
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue|Where-Object{$_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -like '*server.py*' -and $_.CommandLine -like "*--port $Port*"}|ForEach-Object{Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}
}
function Start-App{$p=Start-Process -FilePath $PythonExe -WorkingDirectory $ProjectDir -ArgumentList "-u server.py --host 0.0.0.0 --port $Port" -RedirectStandardOutput (Join-Path $LogDir 'server.log') -RedirectStandardError (Join-Path $LogDir 'server-error.log') -WindowStyle Hidden -PassThru;Set-Content -LiteralPath $PidFile -Value $p.Id -Encoding ASCII}
function Test-Code{$p=@('rule_engine.py','source_manager.py','server.py','scripts\sync_sources.py')|ForEach-Object{Join-Path $ProjectDir $_};& $PythonExe -m py_compile $p;if($LASTEXITCODE -ne 0){throw "Python syntax check failed: $LASTEXITCODE"}}
function Test-Health{for($i=1;$i -le 10;$i++){try{$r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri "http://127.0.0.1:$Port/api/sources";if($r.StatusCode -eq 200){return}}catch{};Start-Sleep 2};throw 'Service health check failed after 20 seconds.'}
function Install-Worker{
  Assert-Admin
  $a="-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Mode Worker -ProjectDir `"$ProjectDir`" -PythonExe `"$PythonExe`" -TaskName `"$TaskName`" -Repo `"$Repo`" -Port $Port"
  $action=New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument $a -WorkingDirectory $ProjectDir
  $trigger=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
  $settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -User SYSTEM -RunLevel Highest -Force|Out-Null
  Log "installed task=$TaskName project=$ProjectDir python=$PythonExe";Start-ScheduledTask -TaskName $TaskName;Write-Host "Installed $TaskName. Log: $LogFile"
}
function Worker{
  Log "worker started project=$ProjectDir python=$PythonExe port=$Port"
  if(-not(Test-Path (Join-Path $ProjectDir 'server.py'))){throw "Invalid ProjectDir: $ProjectDir"};if(-not(Test-Path $PythonExe)){throw "Python not found: $PythonExe"}
  try{$lock=[IO.File]::Open($LockFile,'OpenOrCreate','ReadWrite','None')}catch{Log 'another worker is active';return}
  try{
    $sha=Remote-Sha;$old='';if(Test-Path $State){try{$old=[string](Get-Content $State -Raw|ConvertFrom-Json).sha}catch{}};if($sha -eq $old){Log "unchanged sha=$sha";return}
    $stage=Join-Path $env:TEMP "novel-deploy-$sha";$backup=Join-Path $ProjectDir ("backups\deploy_"+(Get-Date -Format yyyyMMdd_HHmmss));Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue;New-Item -ItemType Directory -Force -Path $stage,$backup|Out-Null
    foreach($f in $Files){$s=Join-Path $stage ($f -replace '/','\');New-Item -ItemType Directory -Force -Path (Split-Path $s)|Out-Null;$ok=$false;foreach($b in $Bases){try{Invoke-WebRequest -UseBasicParsing -Uri "$b/$sha/$f" -OutFile $s -TimeoutSec 30;if((Get-Item $s).Length -lt 20){throw 'file too small'};$ok=$true;break}catch{Log "download failed file=$f base=$b error=$($_.Exception.Message)"}};if(-not $ok){throw "All download endpoints failed for $f"}}
    foreach($f in $Files){$t=Join-Path $ProjectDir ($f -replace '/','\');if(Test-Path $t){$d=Join-Path $backup ($f -replace '/','\');New-Item -ItemType Directory -Force -Path (Split-Path $d)|Out-Null;Copy-Item $t $d -Force}}
    try{
      foreach($f in $Files){$s=Join-Path $stage ($f -replace '/','\');$t=Join-Path $ProjectDir ($f -replace '/','\');New-Item -ItemType Directory -Force -Path (Split-Path $t)|Out-Null;Copy-Item $s $t -Force}
      Test-Code;& $PythonExe (Join-Path $ProjectDir 'scripts\sync_sources.py') --probe-key test >> $LogFile 2>&1;$sync=$LASTEXITCODE
      Stop-App;Start-App;Test-Health
      @{sha=$sha;deployed_at=(Get-Date).ToString('s');sync_exit=$sync}|ConvertTo-Json|Set-Content -LiteralPath $State -Encoding UTF8;Log "deployed sha=$sha sync_exit=$sync backup=$backup"
    }catch{foreach($f in $Files){$s=Join-Path $backup ($f -replace '/','\');$t=Join-Path $ProjectDir ($f -replace '/','\');if(Test-Path $s){Copy-Item $s $t -Force}};Stop-App;Start-App;Log "FAILED sha=$sha error=$($_.Exception.Message) restored=$backup";throw}
    finally{Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue}
  }finally{if($lock){$lock.Dispose()};Remove-Item $LockFile -Force -ErrorAction SilentlyContinue}
}
try{if($Mode -eq 'Install'){Install-Worker}else{Worker}}catch{try{Log "fatal mode=$Mode error=$($_.Exception.Message)"}catch{Write-Error $_.Exception.Message};exit 1}
