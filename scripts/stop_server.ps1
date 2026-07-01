# Stop LLM-QAuto web server and any uvicorn reload workers left on port 8080.
param(
    [int]$Port = 8080
)

$ErrorActionPreference = "SilentlyContinue"

Write-Host "Stopping LLM-QAuto web server (port $Port)..." -ForegroundColor Cyan

$targets = @{}
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match 'web_server\.py' } |
    ForEach-Object { $targets[$_.ProcessId] = $_.CommandLine }

netstat -ano | Select-String ":$Port\s+.*LISTENING" | ForEach-Object {
    if ($_.Line -match '\s(\d+)\s*$') {
        $listenerPid = [int]$Matches[1]
        if (-not $targets.ContainsKey($listenerPid)) {
            $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$listenerPid"
            if ($proc) { $targets[$listenerPid] = $proc.CommandLine }
        }
    }
}

if ($targets.Count -eq 0) {
    Write-Host "No web_server process or listener on port $Port." -ForegroundColor Green
    exit 0
}

foreach ($entry in $targets.GetEnumerator()) {
    Write-Host "  taskkill /F /T /PID $($entry.Key)"
    & taskkill /F /T /PID $entry.Key | Out-Null
}

Start-Sleep -Seconds 1
$stillListening = netstat -ano | Select-String ":$Port\s+.*LISTENING"
if ($stillListening) {
    Write-Host "Port $Port is still in use. Close the terminal running web_server.py or run as admin:" -ForegroundColor Yellow
    Write-Host "  taskkill /F /T /PID <pid>"
    exit 1
}

Write-Host "Done. Port $Port is free. Restart with: python web_server.py" -ForegroundColor Green
