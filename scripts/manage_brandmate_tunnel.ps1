[CmdletBinding()]
param(
    [ValidateSet("start", "status", "url", "logs", "stop")]
    [string]$Action = "start",

    [ValidateRange(10, 180)]
    [int]$WaitSeconds = 90
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ComposeFile = Join-Path $ProjectRoot "docker-compose.tunnel.yml"
$ComposePrefix = @("compose", "-f", $ComposeFile)
$TunnelUrlPattern = "https://[a-z0-9-]+\.trycloudflare\.com"
$ProxyPort = if ($env:BRANDMATE_TUNNEL_PROXY_PORT) {
    [int]$env:BRANDMATE_TUNNEL_PROXY_PORT
}
else {
    8787
}

if ($ProxyPort -lt 1 -or $ProxyPort -gt 65535) {
    throw "BRANDMATE_TUNNEL_PROXY_PORT must be between 1 and 65535."
}

function Invoke-Compose {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [switch]$Capture,
        [switch]$AllowFailure
    )

    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        # Docker writes normal pull/progress messages to stderr. Capture both
        # streams and decide success from the native process exit code.
        $Output = & docker @ComposePrefix @Arguments 2>&1
        $ExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }

    if (-not $AllowFailure -and $ExitCode -ne 0) {
        throw "docker compose failed (exit $ExitCode):`n$($Output | Out-String)"
    }

    if ($Capture) {
        return ($Output | Out-String)
    }

    $Output | ForEach-Object { Write-Host $_ }
}

function Assert-LocalEndpoint {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$Url
    )

    try {
        $Response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
    }
    catch {
        throw "$Name is not reachable at $Url. Start BrandMate in another terminal with .\start-brandmate.cmd -NoBrowser, keep that terminal open, and then open the tunnel. $($_.Exception.Message)"
    }

    if ($Response.StatusCode -lt 200 -or $Response.StatusCode -ge 400) {
        throw "$Name returned HTTP $($Response.StatusCode) at $Url."
    }
}

function Get-TunnelUrl {
    $Logs = Invoke-Compose -Arguments @("logs", "--no-color", "cloudflared") -Capture -AllowFailure
    $Matches = [regex]::Matches($Logs, $TunnelUrlPattern)

    if ($Matches.Count -eq 0) {
        return $null
    }

    return $Matches[$Matches.Count - 1].Value
}

function Get-PublicDnsState {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url
    )

    try {
        $TunnelUri = [uri]$Url
        $DnsName = [uri]::EscapeDataString($TunnelUri.DnsSafeHost)
        $Result = Invoke-RestMethod `
            -Uri "https://dns.google/resolve?name=$DnsName&type=A" `
            -TimeoutSec 10

        $Addresses = @()
        if ($null -ne $Result.PSObject.Properties["Answer"]) {
            $Addresses = @(
                $Result.Answer |
                    Where-Object { [int]$_.type -eq 1 } |
                    ForEach-Object { [string]$_.data }
            )
        }

        if ([int]$Result.Status -eq 0 -and $Addresses.Count -gt 0) {
            return [pscustomobject]@{
                Status = "active"
                Addresses = $Addresses
            }
        }

        if ([int]$Result.Status -eq 3) {
            return [pscustomobject]@{
                Status = "missing"
                Addresses = @()
            }
        }
    }
    catch {
        # Public DNS verification is a fallback for a broken local DNS resolver.
    }

    return [pscustomobject]@{
        Status = "unknown"
        Addresses = @()
    }
}

function Test-TunnelViaPublicDns {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [Parameter(Mandatory = $true)]
        [pscustomobject]$DnsState
    )

    if ($DnsState.Status -ne "active") {
        return $false
    }

    $Curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if (-not $Curl) {
        return $false
    }

    $TunnelUri = [uri]$Url
    foreach ($Address in $DnsState.Addresses) {
        $Resolve = "{0}:443:{1}" -f $TunnelUri.DnsSafeHost, $Address
        $StatusCode = & $Curl.Source `
            --silent `
            --show-error `
            --output NUL `
            --write-out "%{http_code}" `
            --connect-timeout 10 `
            --max-time 15 `
            --resolve $Resolve `
            "$Url/manifest.webmanifest" 2>$null

        if ($LASTEXITCODE -eq 0 -and ($StatusCode | Out-String).Trim() -eq "200") {
            return $true
        }
    }

    return $false
}

function Test-TunnelConnectionRegistered {
    $Logs = Invoke-Compose `
        -Arguments @("logs", "--no-color", "--tail", "120", "cloudflared") `
        -Capture `
        -AllowFailure

    return $Logs -match "Registered tunnel connection"
}

function Wait-ForPublicTunnel {
    param(
        [Parameter(Mandatory = $true)]
        [int]$TimeoutSeconds
    )

    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $LastUrl = $null

    while ((Get-Date) -lt $Deadline) {
        $LastUrl = Get-TunnelUrl
        if ($LastUrl) {
            try {
                $Response = Invoke-WebRequest `
                    -Uri "$LastUrl/manifest.webmanifest" `
                    -UseBasicParsing `
                    -TimeoutSec 10
                if ($Response.StatusCode -eq 200) {
                    return $LastUrl
                }
            }
            catch {
                # A new quick-tunnel hostname can need a few seconds of DNS warm-up.
            }

            $DnsState = Get-PublicDnsState -Url $LastUrl
            if (Test-TunnelViaPublicDns -Url $LastUrl -DnsState $DnsState) {
                Write-Warning "This PC's local DNS could not open the hostname, but the tunnel was verified through Cloudflare public DNS."
                return $LastUrl
            }

            if (
                $DnsState.Status -eq "active" -and
                (Test-TunnelConnectionRegistered)
            ) {
                Write-Warning "This PC's local DNS could not open the hostname. Cloudflare public DNS and the tunnel connection are ready."
                return $LastUrl
            }
        }

        Start-Sleep -Seconds 2
    }

    $Logs = Invoke-Compose -Arguments @("logs", "--no-color", "--tail", "80", "cloudflared") -Capture -AllowFailure
    throw "The temporary HTTPS tunnel was not ready within $TimeoutSeconds seconds.`n$Logs"
}

switch ($Action) {
    "start" {
        if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
            throw "Docker CLI was not found. Start Docker Desktop and try again."
        }

        & docker info --format "{{.ServerVersion}}" *> $null
        if ($LASTEXITCODE -ne 0) {
            throw "Docker Desktop is not running or the current user cannot access it."
        }

        Assert-LocalEndpoint -Name "BrandMate web" -Url "http://127.0.0.1:5501/"
        Assert-LocalEndpoint -Name "BrandMate API readiness" -Url "http://127.0.0.1:7660/ready"

        Write-Host "Starting the local proxy and temporary HTTPS tunnel..."
        Invoke-Compose -Arguments @("up", "-d", "--pull", "missing")

        Assert-LocalEndpoint `
            -Name "BrandMate local proxy" `
            -Url "http://127.0.0.1:$ProxyPort/__brandmate_proxy_health"

        $TunnelUrl = Wait-ForPublicTunnel -TimeoutSeconds $WaitSeconds
        Write-Host ""
        Write-Host "BrandMate temporary HTTPS URL:"
        Write-Host $TunnelUrl
        Write-Host ""
        Write-Host "Keep these containers running during the presentation."
        Write-Host "Stop them with:"
        Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\manage_brandmate_tunnel.ps1 stop"
    }

    "status" {
        Invoke-Compose -Arguments @("ps") -AllowFailure
        $TunnelUrl = Get-TunnelUrl
        if ($TunnelUrl) {
            $DnsState = Get-PublicDnsState -Url $TunnelUrl
            Write-Host ""
            if ($DnsState.Status -eq "active") {
                Write-Host "Current temporary HTTPS URL: $TunnelUrl"
            }
            elseif ($DnsState.Status -eq "missing") {
                Write-Warning "A tunnel URL remains in the logs, but it is no longer present in public DNS. Run stop and then start."
            }
            else {
                Write-Warning "A tunnel URL was found, but public DNS could not be checked: $TunnelUrl"
            }
        }
        else {
            Write-Host ""
            Write-Host "No active temporary HTTPS URL was found."
        }
    }

    "url" {
        $TunnelUrl = Get-TunnelUrl
        if (-not $TunnelUrl) {
            throw "No active temporary HTTPS URL was found. Run the start action first."
        }

        $DnsState = Get-PublicDnsState -Url $TunnelUrl
        if ($DnsState.Status -eq "missing") {
            throw "The tunnel URL in the logs is no longer valid. Run stop and then start."
        }
        if ($DnsState.Status -eq "unknown") {
            Write-Warning "Public DNS could not be checked. Returning the latest URL from the tunnel logs."
        }

        Write-Output $TunnelUrl
    }

    "logs" {
        Invoke-Compose -Arguments @("logs", "--no-color", "--tail", "120")
    }

    "stop" {
        Invoke-Compose -Arguments @("down", "--remove-orphans")
        Write-Host "The BrandMate temporary HTTPS tunnel has stopped."
        Write-Host "Its trycloudflare.com URL is no longer valid."
    }
}
