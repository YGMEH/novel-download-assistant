# Frontend updater for the Windows ECS deployment.
# Downloads a candidate file first, validates it, then replaces index.html atomically.
$ErrorActionPreference = 'Stop'

$target = 'C:\novel\novel-download-assistant-main\index.html'
$temp = "$target.download"
$backup = "$target.bak"
$url = 'https://ghfast.top/https://raw.githubusercontent.com/YGMEH/novel-download-assistant/main/index.html'

try {
    $dir = Split-Path -Parent $target
    if (-not (Test-Path $dir)) { throw "项目目录不存在：$dir" }

    Invoke-WebRequest -Uri $url -OutFile $temp -UseBasicParsing -TimeoutSec 30
    $item = Get-Item $temp
    if ($item.Length -lt 10000) { throw "下载文件过小：$($item.Length) 字节" }

    $head = [System.IO.File]::ReadAllText($temp, [System.Text.Encoding]::UTF8).Substring(0, 15)
    if ($head -notmatch '<!DOCTYPE|<html') { throw '下载内容不是 HTML，已取消替换' }

    $newHash = (Get-FileHash $temp -Algorithm SHA256).Hash
    $oldHash = if (Test-Path $target) { (Get-FileHash $target -Algorithm SHA256).Hash } else { '' }
    if ($newHash -eq $oldHash) {
        Remove-Item $temp -Force
        exit 0
    }

    if (Test-Path $target) { Copy-Item $target $backup -Force }
    Move-Item $temp $target -Force
    Add-Content -Path (Join-Path $dir 'frontend-updater.log') -Value "$(Get-Date -Format s) updated SHA256=$newHash size=$($item.Length)"
}
catch {
    if (Test-Path $temp) { Remove-Item $temp -Force -ErrorAction SilentlyContinue }
    Add-Content -Path (Join-Path (Split-Path -Parent $target) 'frontend-updater.log') -Value "$(Get-Date -Format s) failed $($_.Exception.Message)"
    exit 1
}
