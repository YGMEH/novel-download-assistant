# 阿里云 Windows Server 2022 部署

目标公网地址（完成后）：`http://47.97.244.28:8765`

## 先在阿里云控制台放行端口

ECS 控制台 → 实例 → 安全组 → 配置规则 → 入方向：

- 协议：TCP
- 端口范围：`8765/8765`
- 授权对象：`0.0.0.0/0`（仅用于首次验证；正式上线建议只开放 80/443）

不要把 RDP 的 `3389` 对所有公网开放；应限制为自己的固定 IP 或使用阿里云控制台连接。

## 推荐方式：下载 ZIP 上传到服务器（避免 ECS 访问 GitHub）

1. 在任意可访问 GitHub 的设备下载仓库 ZIP：
   `https://github.com/YGMEH/novel-download-assistant/archive/refs/heads/main.zip`
2. 用阿里云 Workbench 或远程桌面把 ZIP 上传到服务器并解压为：`C:\novel-download-assistant`
3. 在服务器安装 Python 3.12 x64，并在安装界面勾选 **Add Python to PATH**。
4. 以管理员身份打开 PowerShell，进入项目目录后执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\deploy_windows.ps1
```

脚本会创建 `.venv`、安装 `requirements.txt`、放行 Windows 防火墙 TCP 8765、后台启动服务，并检查本机 `/api/sources`。

## 备用方式：服务器直接拉取

若 ECS 可以访问 GitHub，只需先安装 Python 3.12 x64；然后管理员 PowerShell 执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
Invoke-WebRequest -UseBasicParsing https://raw.githubusercontent.com/YGMEH/novel-download-assistant/main/deploy_windows.ps1 -OutFile C:\deploy_windows.ps1
C:\deploy_windows.ps1
```

## 完成后的检查

在 ECS PowerShell：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765/api/sources
Get-Content C:\novel-download-assistant\logs\server.log -Tail 60
Get-Content C:\novel-download-assistant\logs\server-error.log -Tail 60
```

再从手机流量或其他外网浏览器打开：`http://47.97.244.28:8765`。

若服务器本机正常、外网打不开，优先检查阿里云安全组是否已放行 TCP 8765；其次检查 Windows 防火墙规则。

## 当前限制与后续加固

当前服务没有登录、限流或反向代理。仅适合短期测试。正式公开给他人前，应绑定已备案域名、使用 HTTPS（80/443）、增加请求限流和下载任务并发上限，并定期清理 `downloads/`。
