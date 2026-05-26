param(
    [int]$BackendPort = 8000
)

$ErrorActionPreference = "Stop"

# Use ngrok from Desktop if exists
$desktopNgrok = "$([Environment]::GetFolderPath('Desktop'))\ngrok.exe"
$ngrokPath = if (Test-Path $desktopNgrok) { $desktopNgrok } else { "ngrok" }

Write-Host "Starting ngrok tunnel for Backend on port $BackendPort ..." -ForegroundColor Yellow
Write-Host ""

$ngrokProcess = Start-Process -WindowStyle Hidden -PassThru -FilePath $ngrokPath -ArgumentList "http", $BackendPort

Start-Sleep -Seconds 5

if ($ngrokProcess.HasExited) {
    Write-Host "!! ngrok exited immediately (code $($ngrokProcess.ExitCode))." -ForegroundColor Red
    Write-Host "   Try: ngrok http $BackendPort" -ForegroundColor White
    exit 1
}

Write-Host "Waiting for ngrok URL..." -ForegroundColor Yellow

$deadline = (Get-Date).AddSeconds(90)
$publicUrl = $null
while ((Get-Date) -lt $deadline) {
    try {
        $api = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 5 -ErrorAction Stop
        $tunnel = $api.tunnels | Where-Object { $_.config.addr -like "*$BackendPort*" } | Select-Object -First 1
        if ($tunnel -and $tunnel.public_url) {
            $publicUrl = $tunnel.public_url
            break
        }
    } catch { }
    Start-Sleep -Seconds 2
}

if (-not $publicUrl) {
    Write-Host "!! Failed to get ngrok URL." -ForegroundColor Red
    if ($ngrokProcess -and -not $ngrokProcess.HasExited) { Stop-Process -Id $ngrokProcess.Id -Force }
    exit 1
}

Write-Host ""
Write-Host "======================================================" -ForegroundColor Green
Write-Host "  Backend ngrok tunnel is RUNNING!" -ForegroundColor Green
Write-Host "======================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Public Backend URL:" -ForegroundColor Cyan
Write-Host "  *** $publicUrl ***" -ForegroundColor Green
Write-Host ""
Write-Host "  API Docs: $publicUrl/docs" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Add this to backend/.env:" -ForegroundColor Yellow
Write-Host "  CORS_ORIGINS_STR=http://localhost:5173,http://localhost:5174,http://localhost:3000,$publicUrl" -ForegroundColor White
Write-Host "  TRUSTED_HOSTS_STR=localhost,127.0.0.1,testserver,$($publicUrl -replace 'https?://', '')" -ForegroundColor White
Write-Host ""
Write-Host "  ngrok dashboard: http://127.0.0.1:4040" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Press any key to stop" -ForegroundColor Yellow
Write-Host ""
$null = $host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

if ($ngrokProcess -and -not $ngrokProcess.HasExited) {
    Stop-Process -Id $ngrokProcess.Id -Force
    Write-Host "OK ngrok stopped." -ForegroundColor Green
}
