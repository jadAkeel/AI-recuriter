param(
    [string]$GmailAddress = "",
    [string]$GmailAppPassword = "",
    [int]$FrontendPort = 5173,
    [int]$BackendPort = 8001
)

$ErrorActionPreference = "Stop"

$rootDir = Split-Path -Parent $PSScriptRoot
$frontendDir = Join-Path $rootDir "frontend"
$backendDir = Join-Path $rootDir "backend"
$envPath = Join-Path $backendDir ".env"
$publicTunnelLog = Join-Path $PSScriptRoot "public-tunnel.log"
$publicTunnelErrorLog = Join-Path $PSScriptRoot "public-tunnel-error.log"
$frontendProc = $null
$tunnelProc = $null
$backendProc = $null

function Set-EnvValue {
    param(
        [string]$Path,
        [string]$Key,
        [string]$Value
    )

    $lines = @()
    if (Test-Path $Path) {
        $lines = Get-Content $Path
    }

    $escapedKey = [Regex]::Escape($Key)
    $updated = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^${escapedKey}=") {
            $lines[$i] = "$Key=$Value"
            $updated = $true
        }
    }

    if (-not $updated) {
        $lines += "$Key=$Value"
    }

    Set-Content -Path $Path -Value $lines
}

function Wait-Url {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 60
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return
            }
        } catch {
        }
        Start-Sleep -Seconds 1
    }

    throw "Timed out waiting for $Url"
}

function Wait-PublicTunnelUrl {
    param(
        [string[]]$LogPaths,
        [int]$TimeoutSeconds = 120
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        foreach ($logPath in $LogPaths) {
            if (Test-Path $logPath) {
                $content = Get-Content $logPath -Raw -ErrorAction SilentlyContinue
                if ([string]::IsNullOrWhiteSpace($content)) {
                    continue
                }
                $match = [Regex]::Match($content, "https://[A-Za-z0-9.-]+")
                if ($match.Success) {
                    return $match.Value
                }
            }
        }
        Start-Sleep -Seconds 1
    }

    throw "Timed out waiting for public tunnel URL"
}

function Get-EnvValue {
    param(
        [string]$Path,
        [string]$Key
    )

    if (-not (Test-Path $Path)) {
        return ""
    }

    $escapedKey = [Regex]::Escape($Key)
    foreach ($line in Get-Content $Path) {
        if ($line -match "^${escapedKey}=(.*)$") {
            return $matches[1]
        }
    }

    return ""
}

Set-EnvValue -Path $envPath -Key "SMTP_HOST" -Value "smtp.gmail.com"
Set-EnvValue -Path $envPath -Key "SMTP_PORT" -Value "587"
Set-EnvValue -Path $envPath -Key "SMTP_USERNAME" -Value $GmailAddress
Set-EnvValue -Path $envPath -Key "SMTP_FROM_EMAIL" -Value $GmailAddress
if ($GmailAppPassword) {
    Set-EnvValue -Path $envPath -Key "SMTP_PASSWORD" -Value $GmailAppPassword
}

if (Test-Path $publicTunnelLog) {
    Remove-Item -LiteralPath $publicTunnelLog -Force
}
if (Test-Path $publicTunnelErrorLog) {
    Remove-Item -LiteralPath $publicTunnelErrorLog -Force
}

try {
    $env:VITE_API_PROXY_TARGET = "http://127.0.0.1:$BackendPort"
    $frontendProc = Start-Process -WindowStyle Hidden -PassThru -FilePath "C:\Program Files\nodejs\npm.cmd" -ArgumentList @("run", "dev", "--", "--host", "0.0.0.0", "--port", "$FrontendPort") -WorkingDirectory $frontendDir
    Wait-Url -Url "http://127.0.0.1:$FrontendPort"

    $tunnelProc = Start-Process -WindowStyle Hidden -PassThru -FilePath "C:\Windows\System32\OpenSSH\ssh.exe" -ArgumentList @("-o", "StrictHostKeyChecking=no", "-o", "ServerAliveInterval=60", "-R", "80:127.0.0.1:$FrontendPort", "nokey@localhost.run") -WorkingDirectory $rootDir -RedirectStandardOutput $publicTunnelLog -RedirectStandardError $publicTunnelErrorLog
    $publicUrl = Wait-PublicTunnelUrl -LogPaths @($publicTunnelLog, $publicTunnelErrorLog)
    Set-EnvValue -Path $envPath -Key "APP_BASE_URL" -Value $publicUrl

    $backendProc = Start-Process -WindowStyle Hidden -PassThru -FilePath "C:\Windows\py.exe" -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$BackendPort") -WorkingDirectory $backendDir
    Wait-Url -Url "http://127.0.0.1:$BackendPort/api/v1/health"

    Write-Output ""
    Write-Output "Frontend PID : $($frontendProc.Id)"
    Write-Output "Tunnel PID   : $($tunnelProc.Id)"
    Write-Output "Backend PID  : $($backendProc.Id)"
    Write-Output "Public URL   : $publicUrl"
    Write-Output ""
    if (-not (Get-EnvValue -Path $envPath -Key "SMTP_PASSWORD")) {
        Write-Output "SMTP_PASSWORD is still empty in backend/.env"
        Write-Output "Add your 16-character Gmail App Password, then restart the backend process."
    } else {
        Write-Output "Gmail SMTP is configured."
    }
} catch {
    foreach ($proc in @($backendProc, $tunnelProc, $frontendProc)) {
        if ($proc -and -not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
    throw
}
