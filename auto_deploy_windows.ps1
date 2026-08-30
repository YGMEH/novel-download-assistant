#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Install', 'Worker')][string]$Mode = 'Install',
    [string]$ProjectDir = '',
    [string]$PythonExe = '',
    [string]$TaskName = 'NovelAutoDeploy',
    [string]$Repo = 'YGMEH/novel-download-assistant',
    [int]$Port = 8765
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Resolve-ProjectDir([string]$Requested) {
    if ($Requested) { return [IO.Path]::GetFullPath($Requested) }
    foreach ($candidate in @(
        'C:\Users\Administrator\Downloads\novel_oss',
        'C:\novel\novel-download-assistant-main',
        'C:\novel-download-assistant',
        (Split-Path -Parent $PSCommandPath)
    )) {
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
$DeployLog = Join-Path $LogDir 'auto_deploy.log'
$StateFile = Join-Path $ProjectDir '.auto-deploy-state.json'
$LockFile = Join-Path $ProjectDir '.auto-deploy.lock'
$Files = @(
    'rule_engine.py', 'source_manager.py', 'server.py', 'downloader.py',
    'tomato_source.py', 'index.html', 'requirements.txt', 'scripts/sync_sources.py'
)
$ApiUrls = @(
    "https://api.github.com/repos/$Repo/commits/main",
    "https://ghfast.top/https://api.github.com/repos/$Repo/commits/main"
)
$RawBases = @(
    "https://raw.githubusercontent.com/$Repo",
    "https://cdn.jsdelivr.net/gh/$Repo",
    "https://ghfast.top/https://raw.githubusercontent.com/$Repo"
)
New-Item -ItemType Directory -Force -Path $ProjectDir, $LogDir | Out-Null

function Log([string]$Message) {
    $line = "$(Get-Date -Format s) $Message"
    Add-Content -LiteralPath $DeployLog -Value $line -Encoding UTF8
    if ($Mode -eq 'Install') { Write-Host $line }
}
function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Run Install mode from an elevated Administrator PowerShell window.'
    }
}
function Get-RemoteSha {
    $headers = @{ 'User-Agent' = 'NovelAutoDeploy/2.0'; 'Accept' = 'application/vnd.github+json' }
    foreach ($url in $ApiUrls) {
        try {
            $response = Invoke-RestMethod -UseBasicParsing -Uri $url -Headers $headers -TimeoutSec 20
            if ($response.sha -match '^[0-9a-f]{40}$') { return [string]$response.sha }
        } catch { Log "sha endpoint failed url=$url error=$($_.Exception.Message)" }
    }
    throw 'All GitHub commit endpoints failed.'
}
function Stop-App {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -like "*$ProjectDir*server.py*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
function Start-App {
    $out = Join-Path $LogDir 'server.log'
    $err = Join-Path $LogDir 'server-error.log'
    Start-Process -FilePath $PythonExe -WorkingDirectory $ProjectDir `
        -ArgumentList "-u server.py --host 0.0.0.0 --port $Port" `
        -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden | Out-Null
}
function Test-Code {
    $paths = @('rule_engine.py', 'source_manager.py', 'server.py', 'scripts\sync_sources.py') |
        ForEach-Object { Join-Path $ProjectDir $_ }
    & $PythonExe -m py_compile $paths
    if ($LASTEXITCODE -ne 0) { throw "Python syntax check failed with exit code $LASTEXITCODE." }
}
function Test-Health {
    for ($attempt = 1; $attempt -le 10; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri "http://127.0.0.1:$Port/api/sources"
            if ($response.StatusCode -eq 200) { return }
        } catch { Start-Sleep -Seconds 2 }
    }
    throw 'Service health check failed after 20 seconds.'
}
function Install-Worker {
    Assert-Administrator
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Mode Worker -ProjectDir `"$ProjectDir`" -PythonExe `"$PythonExe`" -TaskName `"$TaskName`" -Repo `"$Repo`" -Port $Port"
    $action = New-ScheduledTaskAction -Execute 'PowerShell.exe' -Argument $arguments -WorkingDirectory $ProjectDir
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -User 'SYSTEM' -RunLevel Highest -Force | Out-Null
    Log "installed task=$TaskName project=$ProjectDir python=$PythonExe"
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Installed $TaskName. Log: $DeployLog"
}
function Deploy-Revision {
    Log "worker started project=$ProjectDir python=$PythonExe port=$Port"
    if (-not (Test-Path (Join-Path $ProjectDir 'server.py'))) { throw "Invalid ProjectDir: $ProjectDir" }
    if (-not (Test-Path $PythonExe)) { throw "Python not found: $PythonExe" }
    try { $lock = [IO.File]::Open($LockFile, 'OpenOrCreate', 'ReadWrite', 'None') }
    catch { Log 'another worker is active'; return }
    try {
        $remoteSha = Get-RemoteSha
        $oldSha = ''
        if (Test-Path $StateFile) {
            try { $oldSha = [string](Get-Content $StateFile -Raw | ConvertFrom-Json).sha } catch {}
        }
        if ($remoteSha -eq $oldSha) { Log "unchanged sha=$remoteSha"; return }
        $stage = Join-Path $env:TEMP "novel-deploy-$remoteSha"
        $backup = Join-Path $ProjectDir ("backups\deploy_" + (Get-Date -Format 'yyyyMMdd_HHmmss'))
        Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Force -Path $stage, $backup | Out-Null
        foreach ($file in $Files) {
            $stageFile = Join-Path $stage ($file -replace '/', '\')
            New-Item -ItemType Directory -Force -Path (Split-Path $stageFile) | Out-Null
            $downloaded = $false
            foreach ($base in $RawBases) {
                try {
                    Invoke-WebRequest -UseBasicParsing -Uri "$base/$remoteSha/$file" -OutFile $stageFile -TimeoutSec 30
                    if ((Get-Item $stageFile).Length -lt 20) { throw 'downloaded file is too small' }
                    $downloaded = $true; break
                } catch { Log "download failed file=$file base=$base error=$($_.Exception.Message)" }
            }
            if (-not $downloaded) { throw "All download endpoints failed for $file." }
        }
        foreach ($file in $Files) {
            $target = Join-Path $ProjectDir ($file -replace '/', '\')
            if (Test-Path $target) {
                $saved = Join-Path $backup ($file -replace '/', '\')
                New-Item -ItemType Directory -Force -Path (Split-Path $saved) | Out-Null
                Copy-Item $target $saved -Force
            }
        }
        try {
            foreach ($file in $Files) {
                $source = Join-Path $stage ($file -replace '/', '\')
                $target = Join-Path $ProjectDir ($file -replace '/', '\')
                New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
                Copy-Item $source $target -Force
            }
            Test-Code
            $sync = Join-Path $ProjectDir 'scripts\sync_sources.py'
            & $PythonExe $sync --probe-key 'test' >> $DeployLog 2>&1
            $syncCode = $LASTEXITCODE
            Stop-App; Start-App; Test-Health
            @{ sha=$remoteSha; deployed_at=(Get-Date).ToString('s'); sync_exit=$syncCode } |
                ConvertTo-Json | Set-Content -LiteralPath $StateFile -Encoding UTF8
            Log "deployed sha=$remoteSha sync_exit=$syncCode backup=$backup"
        } catch {
            foreach ($file in $Files) {
                $saved = Join-Path $backup ($file -replace '/', '\')
                $target = Join-Path $ProjectDir ($file -replace '/', '\')
                if (Test-Path $saved) { Copy-Item $saved $target -Force }
            }
            Stop-App; Start-App
            Log "FAILED sha=$remoteSha error=$($_.Exception.Message) restored=$backup"
            throw
        } finally { Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue }
    } finally {
        if ($lock) { $lock.Dispose() }
        Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
    }
}

try {
    if ($Mode -eq 'Install') { Install-Worker } else { Deploy-Revision }
} catch {
    try { Log "fatal mode=$Mode error=$($_.Exception.Message)" } catch { Write-Error $_.Exception.Message }
    exit 1
}
