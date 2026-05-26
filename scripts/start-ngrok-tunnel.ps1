param(
    [int]$FrontendPort = 5173,
    [int]$BackendPort = 8000,
    [switch]$NoOllama,
    [switch]$NoRedis
)

$ErrorActionPreference = "Stop"
$rootDir = Split-Path -Parent $PSScriptRoot
$frontendDir = Join-Path $rootDir "frontend"
$backendDir = Join-Path $rootDir "backend"
$envPath = Join-Path $backendDir ".env"
$logDir = Join-Path $rootDir "logs"
$null = New-Item -ItemType Directory -Path $logDir -Force

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$ngrokLog = Join-Path $logDir "ngrok-$timestamp.log"
$frontendLog = Join-Path $logDir "frontend-$timestamp.log"
$backendLog = Join-Path $logDir "backend-$timestamp.log"

Write-Output ""
Write-Output "=== AI Recruiter - Public Tunnel Launcher (ngrok) ==="
Write-Output ""

function Write-Step   { param([string]$M) Write-Host "  >> $M" -ForegroundColor Yellow }
function Write-Success { param([string]$M) Write-Host "  OK $M" -ForegroundColor Green }
function Write-Error   { param([string]$M) Write-Host "  !! $M" -ForegroundColor Red }
function Write-Info    { param([string]$M) Write-Host "     $M" -ForegroundColor White }

function Test-CommandAvailable {
    param([string]$Command)
    $null = Get-Command $Command -ErrorAction SilentlyContinue
    return $?
}

function Update-EnvValue {
    param([string]$Key, [string]$Value)
    $lines = @()
    if (Test-Path $envPath) { $lines = Get-Content $envPath }
    $escapedKey = [Regex]::Escape($Key)
    $updated = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^${escapedKey}=") {
            $lines[$i] = "$Key=$Value"
            $updated = $true
        }
    }
    if (-not $updated) { $lines += "$Key=$Value" }
    Set-Content -Path $envPath -Value $lines -Encoding ASCII
}

function Kill-ProcessOnPort {
    param([int]$Port)
    $conn = netstat -ano | Select-String "LISTENING" | Select-String ":$Port "
    if ($conn) {
        $items = @($conn)
        $foundPid = $items[0].Line.Trim().Split()[-1]
        $proc = Get-Process -Id $foundPid -ErrorAction SilentlyContinue
        if ($proc -and $proc.ProcessName -ne "ngrok") {
            Write-Info "Killing $($proc.ProcessName) (PID=$foundPid) on port $Port ..."
            Stop-Process -Id $foundPid -Force -ErrorAction SilentlyContinue
        }
    }
}

function Wait-ForUrl {
    param([string]$Url, [int]$TimeoutSeconds = 60)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 3 -ErrorAction Stop
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { return $true }
        } catch { }
        Start-Sleep -Seconds 1.5
    }
    return $false
}

function Get-NgrokUrl {
    param([int]$TimeoutSeconds = 90)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $api = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 5 -ErrorAction Stop
            $tunnel = $api.tunnels | Where-Object { $_.config.addr -like "*$FrontendPort*" } | Select-Object -First 1
            if ($tunnel -and $tunnel.public_url) { return $tunnel.public_url }
        } catch { }
        Start-Sleep -Seconds 2
    }
    return $null
}

# ========== PREREQUISITES ==========
Write-Step "Checking prerequisites..."
$missing = @()
if (-not (Test-CommandAvailable "node")) { $missing += "Node.js" }
if (-not (Test-CommandAvailable "npm")) { $missing += "npm" }
if (-not (Test-CommandAvailable "ngrok")) { $missing += "ngrok" }
if (-not (Test-CommandAvailable "python")) { $missing += "Python" }
if ($missing.Count -gt 0) {
    Write-Error "Missing: $($missing -join ', ')"
    exit 1
}
Write-Success "Node, npm, ngrok, Python found"

# ========== OLLAMA ==========
if (-not $NoOllama) {
    Write-Step "Checking Ollama..."
    $ollama = $null
    try { $ollama = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 5 -ErrorAction Stop } catch { }
    if (-not $ollama) {
        Write-Error "Ollama is not running. Use -NoOllama flag to skip, or start ollama serve"
    } else {
        Write-Success "Ollama running"
        $models = $ollama.models | ForEach-Object { $_.name }
        foreach ($m in @("llama3.2", "gemma3:4b", "nomic-embed-text")) {
            if ($models -notcontains $m) {
                Write-Info "Pulling $m (first time, may take a while)..."
                Start-Process -WindowStyle Hidden -FilePath "ollama" -ArgumentList "pull", $m -Wait
            }
        }
        Write-Success "All Ollama models ready"
    }
} else {
    Write-Info "Ollama check skipped"
}

# ========== REDIS ==========
if (-not $NoRedis -and (Test-CommandAvailable "redis-cli")) {
    try {
        $null = & redis-cli ping 2>&1
        Write-Success "Redis running"
    } catch {
        Write-Info "Redis not installed/running (not critical)"
    }
}

# ========== KILL OLD PROCESSES ==========
Write-Step "Cleaning old processes..."
Kill-ProcessOnPort -Port $FrontendPort
Kill-ProcessOnPort -Port $BackendPort
# Kill any stale ngrok
Get-Process -Name "ngrok" -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Info "Killing old ngrok PID=$($_.Id)"
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2

# ========== INSTALL FRONTEND DEPS ==========
$npmPath = (Get-Command "npm.cmd" -ErrorAction Stop).Source
if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    Write-Step "Installing frontend dependencies..."
    Push-Location $frontendDir
    try { & $npmPath install 2>&1 | Out-Null; Write-Success "Frontend deps installed" } finally { Pop-Location }
}

# ========== START FRONTEND ==========
Write-Step "Starting Frontend (Vite) on port $FrontendPort ..."
$env:VITE_API_PROXY_TARGET = "http://127.0.0.1:$BackendPort"
$feErrLog = "${frontendLog}.err"
$feProcess = Start-Process -WindowStyle Hidden -PassThru -FilePath $npmPath -ArgumentList "run", "dev", "--", "--host", "0.0.0.0", "--port", "$FrontendPort" -WorkingDirectory $frontendDir -RedirectStandardOutput $frontendLog -RedirectStandardError $feErrLog
Start-Sleep -Seconds 3

if (-not (Wait-ForUrl -Url "http://127.0.0.1:$FrontendPort" -TimeoutSeconds 30)) {
    Write-Error "Frontend failed to start. Check: $frontendLog"
    if ($feProcess -and -not $feProcess.HasExited) { Stop-Process -Id $feProcess.Id -Force }
    exit 1
}
Write-Success "Frontend running at http://127.0.0.1:$FrontendPort"

# ========== START NGROK ==========
Write-Step "Starting ngrok tunnel on port $FrontendPort ..."
# Prefer ngrok.exe from Desktop over WindowsApps (which is a stub)
$desktopNgrok = "$([Environment]::GetFolderPath('Desktop'))\ngrok.exe"
$ngrokPath = if (Test-Path $desktopNgrok) { $desktopNgrok } else { (Get-Command "ngrok" -ErrorAction Stop).Source }
Write-Info "ngrok path: $ngrokPath"
$ngrokProcess = Start-Process -WindowStyle Hidden -PassThru -FilePath $ngrokPath -ArgumentList "http", $FrontendPort
Start-Sleep -Seconds 5

if ($ngrokProcess.HasExited) {
    Write-Error "ngrok exited immediately (code $($ngrokProcess.ExitCode))."
    Write-Info "Try running manually: start-process ngrok -argumentlist 'http',$FrontendPort"
    Start-Sleep -Seconds 2
    if ($feProcess -and -not $feProcess.HasExited) { Stop-Process -Id $feProcess.Id -Force }
    exit 1
}

Write-Info "Waiting for ngrok tunnel (may take 15-30s)..."
$publicUrl = Get-NgrokUrl -TimeoutSeconds 90
if (-not $publicUrl) {
    Write-Error "ngrok URL not found at http://127.0.0.1:4040/api/tunnels"
    Write-Info "Check if ngrok is authenticated: ngrok config check"
    Write-Info "Or run manually: ngrok http $FrontendPort"
    if ($ngrokProcess -and -not $ngrokProcess.HasExited) { Stop-Process -Id $ngrokProcess.Id -Force }
    if ($feProcess -and -not $feProcess.HasExited) { Stop-Process -Id $feProcess.Id -Force }
    exit 1
}
Write-Success "ngrok public URL: $publicUrl"

# ========== UPDATE .ENV ==========
Write-Step "Updating backend .env ..."
Update-EnvValue -Key "APP_BASE_URL" -Value $publicUrl
$domain = ($publicUrl -replace 'https?://', '')
Update-EnvValue -Key "TRUSTED_HOSTS_STR" -Value "localhost,127.0.0.1,testserver,$domain"
$existingOrigins = if (Test-Path $envPath) { (Get-Content $envPath | Select-String "^CORS_ORIGINS_STR=") -replace "^CORS_ORIGINS_STR=", "" } else { "" }
if ($existingOrigins -and $existingOrigins -notlike "*$publicUrl*") {
    Update-EnvValue -Key "CORS_ORIGINS_STR" -Value "$existingOrigins,$publicUrl"
}
Write-Success "Backend .env updated"

# ========== START BACKEND ==========
Write-Step "Starting Backend (FastAPI) on port $BackendPort ..."
$beErrLog = "${backendLog}.err"
$beProcess = Start-Process -WindowStyle Hidden -PassThru -FilePath "python" -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$BackendPort" -WorkingDirectory $backendDir -RedirectStandardOutput $backendLog -RedirectStandardError $beErrLog
Start-Sleep -Seconds 3

if (-not (Wait-ForUrl -Url "http://127.0.0.1:$BackendPort/api/v1/health" -TimeoutSeconds 45)) {
    Write-Error "Backend failed. Check: $backendLog"
    try { Write-Info "Last lines: $(Get-Content $backendLog -Tail 10 -ErrorAction Stop)" } catch { }
    if ($beProcess -and -not $beProcess.HasExited) { Stop-Process -Id $beProcess.Id -Force }
    if ($ngrokProcess -and -not $ngrokProcess.HasExited) { Stop-Process -Id $ngrokProcess.Id -Force }
    if ($feProcess -and -not $feProcess.HasExited) { Stop-Process -Id $feProcess.Id -Force }
    exit 1
}
Write-Success "Backend running at http://127.0.0.1:$BackendPort"

# ========== FINAL OUTPUT ==========
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  ALL SYSTEMS ARE RUNNING!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  PUBLIC LINK (send this to your friends):" -ForegroundColor Cyan
Write-Host ""
Write-Host "  *** $publicUrl ***" -ForegroundColor Green
Write-Host ""
Write-Host "  Local URLs:" -ForegroundColor Cyan
Write-Host "    Frontend : http://127.0.0.1:$FrontendPort"
Write-Host "    Backend  : http://127.0.0.1:$BackendPort"
Write-Host "    API Docs : http://127.0.0.1:$BackendPort/docs"
Write-Host "    ngrok UI : http://127.0.0.1:4040"
Write-Host ""
Write-Host "  Process IDs: FE=$($feProcess.Id)  BE=$($beProcess.Id)  ngrok=$($ngrokProcess.Id)" -ForegroundColor Cyan
Write-Host "  Logs: $logDir" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Press any key to shut down everything" -ForegroundColor Yellow
Write-Host ""
$null = $host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

# ========== CLEANUP ==========
Write-Step "Shutting down..."
@($beProcess, $feProcess, $ngrokProcess) | ForEach-Object {
    if ($_ -and -not $_.HasExited) { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
}
Write-Success "All stopped. Goodbye!"
