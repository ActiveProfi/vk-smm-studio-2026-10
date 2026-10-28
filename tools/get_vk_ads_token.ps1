# Get VK Ads access_token / refresh_token (Client Credentials Grant).
# Docs: https://ads.vk.ru/doc/api/info/Authorization (RU: Авторизация в API)
#
# Required in .env:
#   VK_ADS_CLIENT_ID=...
#   VK_ADS_CLIENT_SECRET=...
#
# Writes into .env:
#   VK_ADS_TOKEN=...
#   VK_ADS_REFRESH_TOKEN=...
#   VK_ADS_ACCESS_TOKEN=...
#
# Run:
#   powershell -ExecutionPolicy Bypass -File ".\tools\get_vk_ads_token.ps1"

param(
    [switch] $Quiet
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = if ((Split-Path -Leaf $scriptDir) -eq "tools") { Split-Path -Parent $scriptDir } else { $scriptDir }
$envPath = Join-Path $projectRoot ".env"

if (-not (Test-Path $envPath)) {
    Write-Error "File .env not found: $envPath"
    exit 1
}

function Read-DotEnv([string] $path) {
    $map = @{}
    Get-Content -LiteralPath $path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $pair = $line -split "=", 2
        if ($pair.Count -eq 2) {
            $map[$pair[0].Trim()] = $pair[1].Trim().Trim('"').Trim("'")
        }
    }
    return $map
}

function Set-DotEnvValue([string] $path, [string] $key, [string] $value) {
    $lines = @(Get-Content -LiteralPath $path -Encoding UTF8)
    $found = $false
    $out = foreach ($line in $lines) {
        if ($line -match ("^\s*" + [regex]::Escape($key) + "\s*=")) {
            $found = $true
            "$key=$value"
        } else {
            $line
        }
    }
    if (-not $found) {
        $out = @($out) + @("", "$key=$value")
    }
    Set-Content -LiteralPath $path -Value $out -Encoding UTF8
}

$envMap = Read-DotEnv $envPath
$clientId = $envMap["VK_ADS_CLIENT_ID"]
$clientSecret = $envMap["VK_ADS_CLIENT_SECRET"]

if (-not $clientId) {
    Write-Error "VK_ADS_CLIENT_ID is empty in .env"
    exit 1
}
if (-not $clientSecret) {
    Write-Error "VK_ADS_CLIENT_SECRET is empty in .env"
    exit 1
}

Write-Host "Requesting token from ads.vk.ru (grant_type=client_credentials)..."

$body = @{
    grant_type    = "client_credentials"
    client_id     = $clientId
    client_secret = $clientSecret
}

try {
    $resp = Invoke-RestMethod `
        -Method Post `
        -Uri "https://ads.vk.ru/api/v2/oauth2/token.json" `
        -ContentType "application/x-www-form-urlencoded" `
        -Body $body
} catch {
    Write-Host ""
    Write-Host "Token request failed." -ForegroundColor Red
    Write-Host $_.Exception.Message
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
        Write-Host $_.ErrorDetails.Message
    }
    Write-Host ""
    Write-Host "Common causes:"
    Write-Host "  - wrong client_id or client_secret"
    Write-Host "  - API access not approved / blocked"
    Write-Host "  - token limit (max 5) - delete old tokens"
    exit 1
}

$access = [string]$resp.access_token
$refresh = [string]$resp.refresh_token
$expires = $resp.expires_in

if (-not $access) {
    Write-Error "No access_token in response"
    exit 1
}

Set-DotEnvValue $envPath "VK_ADS_TOKEN" $access
if ($refresh) {
    Set-DotEnvValue $envPath "VK_ADS_REFRESH_TOKEN" $refresh
}
Set-DotEnvValue $envPath "VK_ADS_ACCESS_TOKEN" $access
$expiresAt = [int](([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) + ([int]($expires -as [int])))
if (-not $expires) { $expiresAt = [int](([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) + 86400) }
Set-DotEnvValue $envPath "VK_ADS_TOKEN_EXPIRES_AT" "$expiresAt"

Write-Host ""
Write-Host "OK. Tokens saved to .env:" -ForegroundColor Green
Write-Host "  VK_ADS_TOKEN"
Write-Host "  VK_ADS_ACCESS_TOKEN"
if ($refresh) { Write-Host "  VK_ADS_REFRESH_TOKEN" }
if ($expires) { Write-Host ("  access_token lifetime: about {0} seconds (~1 day)" -f $expires) }
Write-Host ""
Write-Host "Next:"
Write-Host "  1) Restart webapp (run_webapp.py)"
Write-Host "  2) Open menu Reklama / Ads"
Write-Host ""

if (-not $Quiet) {
    if ($access.Length -gt 12) {
        $preview = $access.Substring(0, 6) + "...***..." + $access.Substring($access.Length - 4)
    } else {
        $preview = "***"
    }
    Write-Host ("access_token preview: {0} (full value only in .env)" -f $preview)
}
