#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Install', 'Worker')][string]$Mode = 'Install',
    [string]$ProjectDir = '',
    [string]$PackageUrl = '',
    [string]$ChecksumUrl = '',
    [string]$PythonExe = '',
    [string]$TaskName = 'NovelOssDeploy',
    [int]$Port = 8765
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
function Resolve-ProjectDir([string]$Requested) {
    if ($Requested) { return [IO.Path]::GetFullPath($Requested) }
    foreach ($candidate in @('C:\Users\Administrator\Downloads\novel_oss','C:\novel\novel-download-assistant-main','C:\novel-download-assistant',(Split-Path -Parent $PSCommandPath))) {
        if (Test-Path (Join-Path $candidate 'server.py')) { return $candidate }
    }
    throw 'ProjectDir was not supplied and no installation containing server.py was found.'
}
$ProjectDir = Resolve-ProjectDir $ProjectDir
if (-not $PythonExe) {
    $venvPython = Join-Path $ProjectDir '.venv\Scripts\python.exe'
    if (Test-Path $venvPython) { $PythonExe = $venvPython }
    elseif (Test-Path 'C:\Python312\python.exe') { $PythonExe = 'C:\Python312\python.exe' }
    else { throw 'PythonExe was not supplied and Python was not found.' }
}
$LogDir = Join-Path $ProjectDir 'logs'
$DeployLog = Join-Path $LogDir 'oss_deploy.log'
$StateFile = Join-Path $ProjectDir '.oss-deploy-state.json'
$LockFile = Join-Path $ProjectDir '.oss-deploy.lock'
$ProgramFiles = @('rule_engine.py','source_manager.py','server.py','downloader.py','tomato_source.py','index.html','requirements.txt','scripts')
New-Item -ItemType Directory -Force -Path $ProjectDir,$LogDir | Out-Null
function Log([string]$Message) {
    $line = "$(Get-Date -Format s) $Message"
    Add-Content -LiteralPath $DeployLog -Value $line -Encoding UTF8
    if ($Mode -eq 'Install') { Write-Host $line }
}
function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run Install mode from an elevated Administrator PowerShell window.' }
}
function Stop-App {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -like "*$ProjectDir*server.py*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
function Start-App {
    Start-Process -FilePath $PythonExe -WorkingDirectory $ProjectDir -ArgumentList "-u server.py --host 0.0.0.0 --port $Port" -RedirectStandardOutput (Join-Path $LogDir 'server.log') -RedirectStandardError (Join-Path $LogDir 'server-error.log') -WindowStyle Hidden | Out-Null
}
function Test-Code {
    $paths = @('rule_engine.py','source_manager.py','server.py','scripts\sync_sources.py') | ForEach-Object { Join-Path $ProjectDir $_ }
    & $PythonExe -m py_compile $paths
    if ($LASTEXITCODE -ne 0) { throw "Python syntax check failed with exit code $LASTEXITCODE." }
}
function Test-Health {
    for ($attempt=1; $attempt -le 10; $attempt++) {
        try { $response=Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri "http://127.0.0.1:$Port/api/sources"; if ($response.StatusCode -eq 200) { return } } catch { Start-Sleep -Seconds 2 }
    }
    throw 'Service health check failed after 20 seconds.'
}
function Copy-DeploymentFiles([string]$SourceRoot,[string]$DestinationRoot) {
    foreach ($item in $ProgramFiles) {
        $source=Join-Path $SourceRoot $item; $destination=Join-Path $DestinationRoot $item
        if (Test-Path $source -PathType Container) {
            New-Item -ItemType Directory -Force -Path $destination | Out-Null
            Get-ChildItem -LiteralPath $source -Force | ForEach-Object { Copy-Item $_.FullName $destination -Recurse -Force }
        } elseif (Test-Path $source -PathType Leaf) {
            New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
            Copy-Item $source $destination -Force
        }
    }
    $builtinSource=Join-Path $SourceRoot 'sources\builtin'
    if (Test-Path $builtinSource -PathType Container) {
        $builtinDestination=Join-Path $DestinationRoot 'sources\builtin'
        New-Item -ItemType Directory -Force -Path $builtinDestination | Out-Null
        Get-ChildItem -LiteralPath $builtinSource -Force | ForEach-Object { Copy-Item $_.FullName $builtinDestination -Recurse -Force }
    }
}
function Install-Task {
    Assert-Administrator
    if (-not $PackageUrl) { throw 'PackageUrl is required in Install mode.' }
    if (-not $ChecksumUrl) { $ChecksumUrl="$PackageUrl.sha256" }
    $arguments="-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Mode Worker -ProjectDir `"$ProjectDir`" -PackageUrl `"$PackageUrl`" -ChecksumUrl `"$ChecksumUrl`" -PythonExe `"$PythonExe`" -TaskName `"$TaskName`" -Port $Port"
    $action=New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument $arguments -WorkingDirectory $ProjectDir
    $trigger=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
    $settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -User 'SYSTEM' -RunLevel Highest -Force | Out-Null
    Log "installed task=$TaskName project=$ProjectDir python=$PythonExe"
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Installed $TaskName. Log: $DeployLog"
}
function Worker {
    Log "worker started project=$ProjectDir python=$PythonExe port=$Port"
    if (-not $PackageUrl) { throw 'PackageUrl is required in Worker mode.' }
    if (-not (Test-Path $PythonExe)) { throw "Python not found: $PythonExe" }
    try { $lock=[IO.File]::Open($LockFile,'OpenOrCreate','ReadWrite','None') } catch { Log 'another worker is active'; return }
    $work=Join-Path $env:TEMP ("novel-oss-deploy-"+[guid]::NewGuid().ToString('N')); $archive=Join-Path $work 'latest.zip'; $extract=Join-Path $work 'extract'
    try {
        New-Item -ItemType Directory -Force -Path $work,$extract | Out-Null
        Invoke-WebRequest -UseBasicParsing -Uri $PackageUrl -OutFile $archive -TimeoutSec 120
        if ((Get-Item $archive).Length -lt 10000) { throw 'OSS deployment package is too small.' }
        $hash=(Get-FileHash $archive -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($ChecksumUrl) {
            $checksumFile=Join-Path $work 'latest.zip.sha256'; Invoke-WebRequest -UseBasicParsing -Uri $ChecksumUrl -OutFile $checksumFile -TimeoutSec 30
            $expected=((Get-Content $checksumFile -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
            if ($expected -notmatch '^[0-9a-f]{64}$' -or $expected -ne $hash) { throw 'OSS package SHA-256 verification failed.' }
        }
        if (Test-Path $StateFile) { try { if ([string](Get-Content $StateFile -Raw|ConvertFrom-Json).package_sha256 -eq $hash) { Log "unchanged package_sha256=$hash"; return } } catch {} }
        Expand-Archive -Path $archive -DestinationPath $extract -Force
        foreach ($required in @('server.py','index.html','VERSION')) { if (-not (Test-Path (Join-Path $extract $required))) { throw "Package is missing $required." } }
        $version=(Get-Content (Join-Path $extract 'VERSION') -Raw).Trim()
        if ($version -notmatch '^[0-9a-f]{40}$') { throw 'Package VERSION is not a Git commit SHA.' }
        $backup=Join-Path $ProjectDir ("backups\oss_"+(Get-Date -Format 'yyyyMMdd_HHmmss'))
        New-Item -ItemType Directory -Force -Path $backup | Out-Null
        Copy-DeploymentFiles $ProjectDir $backup
        try {
            Copy-DeploymentFiles $extract $ProjectDir
            Test-Code
            & $PythonExe (Join-Path $ProjectDir 'scripts\sync_sources.py') --probe-key 'test' >> $DeployLog 2>&1; $syncCode=$LASTEXITCODE
            Stop-App; Start-App; Test-Health
            @{version=$version;package_sha256=$hash;deployed_at=(Get-Date).ToString('s');sync_exit=$syncCode}|ConvertTo-Json|Set-Content -LiteralPath $StateFile -Encoding UTF8
            Log "deployed version=$version package_sha256=$hash sync_exit=$syncCode backup=$backup"
        } catch {
            Copy-DeploymentFiles $backup $ProjectDir
            Stop-App; Start-App
            Log "FAILED version=$version error=$($_.Exception.Message) restored=$backup"
            throw
        }
    } finally {
        Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
        if ($lock) { $lock.Dispose() }
        Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
    }
}
try { if ($Mode -eq 'Install') { Install-Task } else { Worker } } catch { try { Log "fatal mode=$Mode error=$($_.Exception.Message)" } catch { Write-Error $_.Exception.Message }; exit 1 }
