$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$envPath = Join-Path $projectRoot ".env"

$envMap = @{}
if (Test-Path $envPath) {
    Get-Content $envPath | ForEach-Object {
        if ($_ -match '^\s*$' -or $_ -match '^\s*#') { return }
        $pair = $_ -split '=', 2
        if ($pair.Count -eq 2) {
            $envMap[$pair[0].Trim()] = $pair[1].Trim().Trim('"').Trim("'")
        }
    }
}

$clientId = $envMap["VK_APP_ID"]
if (-not $clientId) {
    $clientId = "54572210"
}

$redirectUri = $envMap["VK_REDIRECT_URI"]
if (-not $redirectUri) {
    $redirectUri = "https://localhost"
}

$scope = "wall,photos,groups,video,offline"
$apiVersion = $envMap["VK_API_VERSION"]
if (-not $apiVersion) {
    $apiVersion = "5.199"
}

$encodedRedirect = [System.Uri]::EscapeDataString($redirectUri)
$encodedScope = [System.Uri]::EscapeDataString($scope)
$encodedBlankRedirect = [System.Uri]::EscapeDataString("https://oauth.vk.com/blank.html")

$url = "https://oauth.vk.com/authorize?client_id=$clientId&display=page&redirect_uri=$encodedRedirect&scope=$encodedScope&response_type=token&v=$apiVersion&revoke=1"
$blankUrl = "https://oauth.vk.com/authorize?client_id=$clientId&display=page&redirect_uri=$encodedBlankRedirect&scope=$encodedScope&response_type=token&v=$apiVersion&revoke=1"

Write-Host ""
Write-Host "VK OAuth URL 1 - try this first:"
Write-Host ""
Write-Host $blankUrl
Write-Host ""
Write-Host "VK OAuth URL 2 - redirect from app settings:"
Write-Host ""
Write-Host $url
Write-Host ""
Write-Host "Open URL 1 in browser where VK admin is logged in."
Write-Host "Copy token after access_token= and before expires_in."
Write-Host "Save it in .env as VK_USER_TOKEN=..."
