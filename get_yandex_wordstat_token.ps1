# Обмен кода Yandex OAuth на токен (код ~10 минут, одноразовый).
# Секреты берутся из .env: YANDEX_WORDSTAT_CLIENT_ID, YANDEX_WORDSTAT_CLIENT_SECRET
# Пример: powershell -ExecutionPolicy Bypass -File ".\get_yandex_wordstat_token.ps1" -Code "вставь_свежий_code"
param(
    [Parameter(Mandatory = $true)]
    [string] $Code
)

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $projectRoot ".env"

if (-not (Test-Path $envPath)) {
    Write-Error "Файл .env не найден: $envPath"
    exit 1
}

$envMap = @{}
Get-Content $envPath | ForEach-Object {
    if ($_ -match '^\s*$' -or $_ -match '^\s*#') { return }
    $pair = $_ -split '=', 2
    if ($pair.Count -eq 2) { $envMap[$pair[0].Trim()] = $pair[1].Trim() }
}

$clientId = $envMap["YANDEX_WORDSTAT_CLIENT_ID"]
$clientSecret = $envMap["YANDEX_WORDSTAT_CLIENT_SECRET"]

if (-not $clientId) { Write-Error "В .env нет YANDEX_WORDSTAT_CLIENT_ID."; exit 1 }
if (-not $clientSecret) { Write-Error "В .env нет YANDEX_WORDSTAT_CLIENT_SECRET."; exit 1 }

$body = @{
    grant_type    = "authorization_code"
    code          = $Code
    client_id     = $clientId
    client_secret = $clientSecret
}

Invoke-RestMethod -Method Post -Uri "https://oauth.yandex.ru/token" -ContentType "application/x-www-form-urlencoded" -Body $body
