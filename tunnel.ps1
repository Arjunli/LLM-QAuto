# LLM-QAuto tunnel (Cloudflare Quick Tunnel)
# Usage: start web_server.py first, then run: .\tunnel.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Cloudflared = Join-Path $Root "tools\cloudflared.exe"

if (-not (Test-Path $Cloudflared)) {
    Write-Host "Downloading tools\cloudflared.exe ..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Force -Path (Join-Path $Root "tools") | Out-Null
    Invoke-WebRequest `
        -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" `
        -OutFile $Cloudflared
}

$Port = 8080
$EnvFile = Join-Path $Root ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^\s*WEB_PORT\s*=\s*(\d+)') { $Port = [int]$Matches[1] }
    }
}

$Target = "http://127.0.0.1:$Port"
try {
    $null = Invoke-WebRequest -Uri $Target -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
} catch {
    $LanIp = $null
    try {
        $udp = New-Object System.Net.Sockets.UdpClient
        $udp.Connect("8.8.8.8", 80)
        $LanIp = ($udp.Client.LocalEndPoint).Address.ToString()
        $udp.Close()
    } catch { }
    if ($LanIp) {
        $Target = "http://${LanIp}:$Port"
        Write-Host "127.0.0.1 not reachable, using LAN: $Target" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " LLM-QAuto tunnel (Cloudflare)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Local:  $Target"
Write-Host " Public: https://xxx.trycloudflare.com (printed below)"
Write-Host " Press Ctrl+C to stop"
Write-Host ""

& $Cloudflared tunnel --url $Target
