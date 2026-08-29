#Requires -Version 5.1
#Requires -RunAsAdministrator
<##
.SYNOPSIS
  Install or run the automatic GitHub-to-Windows deployment worker.

  Install once as Administrator:
    powershell -ExecutionPolicy Bypass -File .\auto_deploy_windows.ps1 -Install

  The scheduled worker checks the public main branch every five minutes. It only
  downloads files and restarts the service when the commit SHA changes.
#>
[CmdletBinding()]
param(
    [ValidateSet('Install', 'Worker')]
    [string]$Mode = 'Install',
    [string]$ProjectDir = '',
    [string]$PythonExe = '',
    [string]$TaskName = 'NovelAutoDeploy',
    [string]$Repo = 'YGMEH/novel-download-assistant',
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Resolve-ProjectDir {
    param([string]$Requested)
    if ($Requested) { return $Requested }
    $candidates = @(
        'C:\novel\novel-download-assistant-main',
        'C:\novel-download-assistant',
        (Split-Path -Parent $PSCommandPath)
    )
    foreach ($candidate in $candidates) {
        if (Test-Path (Join-Path $candidate 'server.py')) { return $candidate }
    }
    return 'C:\novel\novel-download-assistant-main'
}

$ProjectDir = Resolve-ProjectDir $ProjectDir
if (-not $PythonExe) {
    $venvPython = Join-Path $ProjectDir '.venv\Scripts\python.exe'
    $PythonExe = if (Test-Path $venvPython) { $venvPython } else { 'C:\Python312\python.exe' }
}
$LogDir = Join-Path $ProjectDir 'logs'
$DeployLog = Join-Path $LogDir 'auto_deploy.log'
$StateFile = Join-Path $ProjectDir '.auto-deploy-state.json'
$ApiUrl = "https://api.github.com/repos/$Repo/commits/main"
$RawBase = "https://raw.githubusercontent.com/$Repo"
$Files = @('rule_engine.py', 'source_manager.py', 'server.py', 'index.html', 'requirements.txt', 'scripts/sync_sources.py')

New-Item -ItemType Directory -Force -Path $ProjectDir, $LogDir | Out-Null

function Log {
    param([string]$Message)
    $line = "$(Get-Date -Format s) $Message"
    Add-Content -LiteralPath $DeployLog -Value $line -Encoding UTF8
    if ($Mode -eq 'Install') { Write-Host $line }
}

function Get-RemoteSha {
    $headers = @{ 'User-Agent' = 'NovelAutoDeploy/1.0'; 'Accept' = 'application/vnd.github+json' }
    $response = Invoke-RestMethod -UseBasicParsing -Uri $ApiUrl -Headers $headers -TimeoutSec 30
    if (-not $response.sha) { throw 'GitHub API 未返回提交 SHA' }
    return [string]$response.sha
}

function Stop-App {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -like "*$ProjectDir*server.py*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Start-App {
    if (-not (Test-Path $PythonExe)) { throw "找不到 Python: $PythonExe" }
    $out = Join-Path $LogDir 'server.log'
    $err = Join-Path $LogDir 'server-error.log'
    Start-Process -FilePath $PythonExe -WorkingDirectory $ProjectDir `
        -ArgumentList "-u server.py --host 0.0.0.0 --port $Port" `
        -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden | Out-Null
}

function Test-App {
    & $PythonExe -m py_compile (Join-Path $ProjectDir 'rule_engine.py') (Join-Path $ProjectDir 'source_manager.py') (Join-Path $ProjectDir 'server.py') (Join-Path $ProjectDir 'scripts\sync_sources.py')
    if ($LASTEXITCODE -ne 0) { throw "Python 语法校验失败，退出码 $LASTEXITCODE" }
}

function Install-Worker {
    $scriptPath = $PSCommandPath
    $action = New-ScheduledTaskAction -Execute 'PowerShell.exe' `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -Mode Worker -ProjectDir `"$ProjectDir`" -PythonExe `"$PythonExe`" -TaskName `"$TaskName`" -Repo `"$Repo`" -Port $Port" `
        -WorkingDirectory $ProjectDir
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -User 'SYSTEM' -RunLevel Highest -Force | Out-Null
    Log "installed task=$TaskName interval=5m project=$ProjectDir"
    & schtasks.exe /Run /TN $TaskName | Out-Null
    Write-Host "自动部署已安装：$TaskName，每5分钟检查一次 GitHub main。"
    Write-Host "首次运行日志：$DeployLog"
}

function Deploy-Revision {
    $remoteSha = Get-RemoteSha
    $oldSha = ''
    if (Test-Path $StateFile) {
        try { $oldSha = [string](Get-Content $StateFile -Raw | ConvertFrom-Json).sha } catch { $oldSha = '' }
    }
    if ($remoteSha -eq $oldSha) { Log "unchanged sha=$remoteSha"; return }

    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $backup = Join-Path $ProjectDir "backups\deploy_$stamp"
    New-Item -ItemType Directory -Force -Path $backup | Out-Null
    foreach ($file in $Files) {
        $target = Join-Path $ProjectDir ($file -replace '/', '\')
        if (Test-Path $target) {
            $dest = Join-Path $backup ($file -replace '/', '\')
            New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
            Copy-Item $target $dest -Force
        }
    }

    try {
        foreach ($file in $Files) {
            $target = Join-Path $ProjectDir ($file -replace '/', '\')
            $temp = "$target.download"
            $url = "$RawBase/$remoteSha/$file"
            Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $temp -TimeoutSec 60
            if ((Get-Item $temp).Length -lt 20) { throw "下载文件过小: $file" }
            Move-Item $temp $target -Force
        }
        Test-App
        $sync = Join-Path $ProjectDir 'scripts\sync_sources.py'
        & $PythonExe $sync --probe-key '蛊真人' >> $DeployLog 2>&1
        $syncCode = $LASTEXITCODE
        Stop-App
        Start-App
        Start-Sleep -Seconds 3
        try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 -Uri "http://127.0.0.1:$Port/api/sources" | Out-Null } catch { throw "服务健康检查失败: $($_.Exception.Message)" }
        @{ sha = $remoteSha; deployed_at = (Get-Date).ToString('s'); sync_exit = $syncCode } |
            ConvertTo-Json | Set-Content -LiteralPath $StateFile -Encoding UTF8
        Log "deployed sha=$remoteSha sync_exit=$syncCode backup=$backup"
    } catch {
        foreach ($file in $Files) {
            $src = Join-Path $backup ($file -replace '/', '\')
            $target = Join-Path $ProjectDir ($file -replace '/', '\')
            if (Test-Path $src) { Copy-Item $src $target -Force }
        }
        Log "FAILED sha=$remoteSha error=$($_.Exception.Message) restored=$backup"
        throw
    }
}

if ($Mode -eq 'Install') {
    Install-Worker
} else {
    try { Deploy-Revision } catch { Log "worker error=$($_.Exception.Message)"; exit 1 }
}
