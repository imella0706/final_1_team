# Legacy Windows launcher kept for team compatibility.

$NoBrowser = $false
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

foreach ($argument in $args) {
    if ($argument -eq "-NoBrowser") {
        $NoBrowser = $true
    }
}

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$ApiDir = Join-Path $Root "apps\api"
$WebDir = Join-Path $Root "apps\web"
$ApiPython = Join-Path $ApiDir ".venv\Scripts\python.exe"
$ComposeFile = Join-Path $Root "docker-compose.api.yml"
$ApiUrl = "http://127.0.0.1:7660"
$WebUrl = "http://127.0.0.1:5501"
$CosyVoiceUrl = "http://127.0.0.1:50000"
$ApiLog = Join-Path $Root "api-server.log"
$ApiErrorLog = Join-Path $Root "api-server-error.log"
$WebLog = Join-Path $Root "web-server.log"
$WebErrorLog = Join-Path $Root "web-server-error.log"
$LocalAdminEmail = if ($env:BRANDMATE_LOCAL_ADMIN_EMAIL) {
    $env:BRANDMATE_LOCAL_ADMIN_EMAIL
} else {
    "admin@admin.com"
}
$LocalAdminPassword = if ($env:BRANDMATE_LOCAL_ADMIN_PASSWORD) {
    $env:BRANDMATE_LOCAL_ADMIN_PASSWORD
} else {
    "brandmateadmin"
}

function Test-Url {
    param([string]$Url)

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    } catch {
        return $false
    }
}

function Wait-Url {
    param(
        [string]$Url,
        [int]$Seconds = 20
    )

    for ($index = 0; $index -lt $Seconds; $index += 1) {
        if (Test-Url $Url) {
            return $true
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Test-Docker {
    try {
        & docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Ensure-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker Desktop is required for the local PostgreSQL database."
    }
    if (Test-Docker) {
        return
    }

    $dockerDesktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path -LiteralPath $dockerDesktop)) {
        throw "Start Docker Desktop, then run start-brandmate.cmd again."
    }

    Write-Host "Starting Docker Desktop..." -ForegroundColor Yellow
    Start-Process -FilePath $dockerDesktop | Out-Null
    for ($index = 0; $index -lt 90; $index += 1) {
        Start-Sleep -Seconds 1
        if (Test-Docker) {
            Write-Host "Docker Desktop is ready." -ForegroundColor Green
            return
        }
    }
    throw "Docker Desktop did not become ready within 90 seconds."
}

function Ensure-Database {
    Ensure-Docker
    Write-Host "Starting local PostgreSQL..."
    & docker compose -f $ComposeFile up -d brandmate-postgres
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to start the local PostgreSQL container."
    }

    for ($index = 0; $index -lt 30; $index += 1) {
        $postgresReady = $false
        try {
            & docker compose -f $ComposeFile exec -T brandmate-postgres `
                pg_isready -U brandmate -d brandmate 2>$null | Out-Null
            $postgresReady = $LASTEXITCODE -eq 0
        } catch {
            $postgresReady = $false
        }
        if ($postgresReady) {
            Write-Host "Local PostgreSQL is ready." -ForegroundColor Green
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "Local PostgreSQL did not become ready within 60 seconds."
}

function Invoke-DatabaseMigrations {
    Write-Host "Applying database migrations..."
    Push-Location $ApiDir
    try {
        & $ApiPython -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) {
            throw "Database migration failed."
        }
    } finally {
        Pop-Location
    }
}

function Test-LocalAdminLogin {
    $loginSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $loginPayload = @{
        email = $LocalAdminEmail
        password = $LocalAdminPassword
        device_name = "Local launcher check"
    } | ConvertTo-Json

    try {
        Invoke-RestMethod `
            -Uri "$ApiUrl/api/v1/auth/login" `
            -Method Post `
            -ContentType "application/json" `
            -Body $loginPayload `
            -WebSession $loginSession `
            -TimeoutSec 15 | Out-Null
        Invoke-RestMethod `
            -Uri "$ApiUrl/api/v1/auth/logout" `
            -Method Post `
            -WebSession $loginSession `
            -TimeoutSec 10 | Out-Null
    } catch {
        throw "Local admin credentials do not match the database: $LocalAdminEmail"
    }
}

function Ensure-LocalAdmin {
    $signupPayload = @{
        email = $LocalAdminEmail
        display_name = "BrandMate Admin"
        password = $LocalAdminPassword
    } | ConvertTo-Json

    try {
        Invoke-RestMethod `
            -Uri "$ApiUrl/api/v1/auth/signup" `
            -Method Post `
            -ContentType "application/json" `
            -Body $signupPayload `
            -TimeoutSec 15 | Out-Null
        Write-Host "Local admin account created: $LocalAdminEmail" -ForegroundColor Green
    } catch {
        $statusCode = if ($_.Exception.Response) {
            [int]$_.Exception.Response.StatusCode
        } else {
            0
        }
        if ($statusCode -ne 409) {
            throw "Local admin account could not be prepared: $($_.Exception.Message)"
        }
    }

    Test-LocalAdminLogin
    Write-Host "Local admin login is ready: $LocalAdminEmail" -ForegroundColor Green
}

if (-not (Test-Path -LiteralPath $ApiPython)) {
    Write-Host "API virtual environment was not found: $ApiPython" -ForegroundColor Red
    Write-Host 'Run: cd apps\api; python -m venv .venv; .venv\Scripts\python -m pip install -e ".[dev]"'
    exit 1
}

$startedProcesses = @()

try {
    Write-Host "Starting BrandMate..." -ForegroundColor Cyan

    Ensure-Database
    Invoke-DatabaseMigrations

    if (Test-Url "$ApiUrl/ready") {
        Write-Host "API is already running: $ApiUrl" -ForegroundColor Yellow
    } else {
        Write-Host "Starting API: $ApiUrl"
        $apiProcess = Start-Process `
            -FilePath $ApiPython `
            -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "7660") `
            -WorkingDirectory $ApiDir `
            -RedirectStandardOutput $ApiLog `
            -RedirectStandardError $ApiErrorLog `
            -PassThru `
            -WindowStyle Hidden
        $startedProcesses += $apiProcess
    }

    if (-not (Wait-Url "$ApiUrl/ready" 25)) {
        Write-Host "API did not become ready. Check these logs:" -ForegroundColor Red
        Write-Host "  $ApiLog"
        Write-Host "  $ApiErrorLog"
        exit 1
    }

    Ensure-LocalAdmin

    try {
        $cosyVoice = Invoke-RestMethod -Uri "$CosyVoiceUrl/health" -TimeoutSec 3
        if ($cosyVoice.ready) {
            Write-Host "Local voice: CosyVoice is ready ($($cosyVoice.model))" -ForegroundColor Green
        } else {
            Write-Host "Local voice: CosyVoice is not ready; OpenAI fallback will be used." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "Local voice: CosyVoice is not running; OpenAI fallback will be used." -ForegroundColor Yellow
    }

    if (Test-Url "$WebUrl/") {
        Write-Host "Web server is already running: $WebUrl" -ForegroundColor Yellow
    } else {
        Write-Host "Starting web server: $WebUrl"
        $webProcess = Start-Process `
            -FilePath $ApiPython `
            -ArgumentList @("-m", "http.server", "5501", "--bind", "127.0.0.1") `
            -WorkingDirectory $WebDir `
            -RedirectStandardOutput $WebLog `
            -RedirectStandardError $WebErrorLog `
            -PassThru `
            -WindowStyle Hidden
        $startedProcesses += $webProcess
    }

    if (-not (Wait-Url "$WebUrl/" 15)) {
        Write-Host "Web server did not become ready. Check these logs:" -ForegroundColor Red
        Write-Host "  $WebLog"
        Write-Host "  $WebErrorLog"
        exit 1
    }

    Write-Host ""
    Write-Host "BrandMate is ready." -ForegroundColor Green
    Write-Host "  Web: $WebUrl/"
    Write-Host "  API: $ApiUrl"
    Write-Host "  Docs: $ApiUrl/docs"
    Write-Host ""

    if (-not $NoBrowser) {
        Start-Process "$WebUrl/"
    }

    if ($startedProcesses.Count -eq 0) {
        Write-Host "All services were already running."
        exit 0
    }

    Write-Host "Close this window or press Ctrl+C to stop services started by this launcher."
    while ($true) {
        Start-Sleep -Seconds 2
        $running = $startedProcesses | Where-Object { -not $_.HasExited }
        if ($startedProcesses.Count -gt 0 -and $running.Count -eq 0) {
            Write-Host "All processes started by this launcher have stopped." -ForegroundColor Yellow
            break
        }
    }
} finally {
    foreach ($process in $startedProcesses) {
        if ($process -and -not $process.HasExited) {
            Write-Host "Stopping server PID $($process.Id)"
            Stop-Process -Id $process.Id -Force
        }
    }
}
