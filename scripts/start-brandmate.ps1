# Legacy Windows launcher kept for team compatibility.
# Standard Linux/GCP/WSL entrypoint: scripts/manage_brandmate_services.sh.
# Move to scripts/legacy or delete only after team agreement.

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
$ApiUrl = "http://127.0.0.1:7660"
$WebUrl = "http://127.0.0.1:5501"
$ApiLog = Join-Path $Root "api-server.log"
$ApiErrorLog = Join-Path $Root "api-server-error.log"
$WebLog = Join-Path $Root "web-server.log"
$WebErrorLog = Join-Path $Root "web-server-error.log"

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

if (-not (Test-Path -LiteralPath $ApiPython)) {
    Write-Host "API 가상환경을 찾을 수 없습니다: $ApiPython" -ForegroundColor Red
    Write-Host "먼저 apps\api 에서 python -m venv .venv 후 pip install -e `".[dev]`" 를 실행해 주세요."
    exit 1
}

$startedProcesses = @()

try {
    Write-Host "BrandMate 실행을 시작합니다." -ForegroundColor Cyan

    if (Test-Url "$ApiUrl/health") {
        Write-Host "API 서버가 이미 실행 중입니다: $ApiUrl" -ForegroundColor Yellow
    } else {
        Write-Host "API 서버 실행 중: $ApiUrl"
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

    if (-not (Wait-Url "$ApiUrl/health" 25)) {
        Write-Host "API 서버가 시간 안에 응답하지 않았습니다. 로그를 확인하세요:" -ForegroundColor Red
        Write-Host "  $ApiLog"
        Write-Host "  $ApiErrorLog"
        exit 1
    }

    if (Test-Url "$WebUrl/") {
        Write-Host "웹 서버가 이미 실행 중입니다: $WebUrl" -ForegroundColor Yellow
    } else {
        Write-Host "웹 서버 실행 중: $WebUrl"
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
        Write-Host "웹 서버가 시간 안에 응답하지 않았습니다. 로그를 확인하세요:" -ForegroundColor Red
        Write-Host "  $WebLog"
        Write-Host "  $WebErrorLog"
        exit 1
    }

    Write-Host ""
    Write-Host "실행 완료" -ForegroundColor Green
    Write-Host "  웹:  $WebUrl/"
    Write-Host "  API: $ApiUrl"
    Write-Host "  문서: $ApiUrl/docs"
    Write-Host ""

    if (-not $NoBrowser) {
        Start-Process "$WebUrl/"
    }

    if ($startedProcesses.Count -eq 0) {
        Write-Host "새로 시작한 서버가 없어 창을 종료합니다. 기존 서버는 계속 실행 중입니다."
        exit 0
    }

    Write-Host "이 창을 닫거나 Ctrl+C를 누르면 이 스크립트가 시작한 서버를 종료합니다."

    while ($true) {
        Start-Sleep -Seconds 2
        $running = $startedProcesses | Where-Object { -not $_.HasExited }
        if ($startedProcesses.Count -gt 0 -and $running.Count -eq 0) {
            Write-Host "시작한 서버 프로세스가 모두 종료되었습니다." -ForegroundColor Yellow
            break
        }
    }
} finally {
    foreach ($process in $startedProcesses) {
        if ($process -and -not $process.HasExited) {
            Write-Host "서버 종료 중: PID $($process.Id)"
            Stop-Process -Id $process.Id -Force
        }
    }
}
