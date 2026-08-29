#requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

$RepoUrl = 'https://github.com/YGMEH/novel-download-assistant.git'
$ZipUrl = 'https://github.com/YGMEH/novel-download-assistant/archive/refs/heads/main.zip'
$AppDir = 'C:\novel-download-assistant'
$Port = 8765

Write-Host '=== 小说下载助手 Windows ECS 部署 ===' -ForegroundColor Cyan
Write-Host "安装目录: $AppDir"
Write-Host "公网端口: $Port"

function Find-Python {
    $candidates = @('py', 'python')
    foreach ($name in $candidates) {
        try {
            $v = & $name --version 2>&1
            if ($LASTEXITCODE -eq 0 -and "$v" -match 'Python 3\.') { return $name }
        } catch {}
    }
    return $null
}

$Python = Find-Python
if (-not $Python) {
    throw '未检测到 Python 3。请先从 python.org 安装 Python 3.11/3.12，并勾选 Add Python to PATH，然后重新运行本脚本。'
}
Write-Host "已检测到 $Python" -ForegroundColor Green

New-Item -ItemType Directory -Force -Path (Split-Path $AppDir) | Out-Null
if (-not (Test-Path (Join-Path $AppDir 'server.py'))) {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git) {
        & git clone $RepoUrl $AppDir
        if ($LASTEXITCODE -ne 0) { throw 'Git 克隆失败。请检查服务器能否访问 GitHub，或先手动下载仓库 ZIP。' }
    } else {
        $zip = Join-Path $env:TEMP 'novel-download-assistant-main.zip'
        $tmp = Join-Path $env:TEMP 'novel-download-assistant-extract'
        Remove-Item $zip -Force -ErrorAction SilentlyContinue
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 -Uri $ZipUrl -OutFile $zip
        Expand-Archive -Path $zip -DestinationPath $tmp -Force
        $src = Join-Path $tmp 'novel-download-assistant-main'
        if (-not (Test-Path (Join-Path $src 'server.py'))) { throw '仓库 ZIP 下载或解压后未找到 server.py。' }
        New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
        Copy-Item (Join-Path $src '*') $AppDir -Recurse -Force
        Remove-Item $zip -Force -ErrorAction SilentlyContinue
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
} elseif (Test-Path (Join-Path $AppDir '.git')) {
    Push-Location $AppDir
    try { & git pull --ff-only } finally { Pop-Location }
}

$Venv = Join-Path $AppDir '.venv'
if (-not (Test-Path (Join-Path $Venv 'Scripts\python.exe'))) {
    & $Python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw '创建 Python 虚拟环境失败。' }
}
$Vpy = Join-Path $Venv 'Scripts\python.exe'
& $Vpy -m pip install --upgrade pip --disable-pip-version-check
& $Vpy -m pip install -r (Join-Path $AppDir 'requirements.txt') --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查网络或 pip 错误信息。' }

New-NetFirewallRule -DisplayName 'Novel Download Assistant TCP 8765' -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Any -ErrorAction SilentlyContinue | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $AppDir 'logs') | Out-Null
$log = Join-Path $AppDir 'logs\server.log'
$err = Join-Path $AppDir 'logs\server-error.log'
Get-Process python,pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $Vpy } | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host '正在启动服务...' -ForegroundColor Yellow
Start-Process -FilePath $Vpy -WorkingDirectory $AppDir -ArgumentList 'server.py --host 0.0.0.0 --port 8765' -RedirectStandardOutput $log -RedirectStandardError $err -WindowStyle Hidden
Start-Sleep -Seconds 3
try {
    $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 -Uri "http://127.0.0.1:$Port/api/sources"
    Write-Host "本机健康检查成功：HTTP $($r.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "本机健康检查失败，请查看：$err" -ForegroundColor Red
    throw
}
Write-Host ''
Write-Host "部署完成。浏览器访问：http://47.97.244.28:$Port" -ForegroundColor Green
Write-Host "日志：$log"
Write-Host '注意：还必须在阿里云安全组入方向放行 TCP 8765；正式使用前建议配置域名、HTTPS、限流和下载清理。' -ForegroundColor Yellow
