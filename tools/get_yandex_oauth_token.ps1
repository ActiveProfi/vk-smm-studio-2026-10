# Обмен кода Yandex OAuth на токен (нужен свежий code, ~10 минут жизни).
# В .env: YANDEX_WORDSTAT_CLIENT_ID, YANDEX_WORDSTAT_CLIENT_SECRET
# Секреты в файлы и чат не вставлять.
param(
    [Parameter(Mandatory = $true)]
    [string] $Code
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = if ((Split-Path -Leaf $scriptDir) -eq "tools") { Split-Path -Parent $scriptDir } else { $scriptDir }
$envPath = Join-Path $projectRoot ".env"

if (-not (Test-Path $envPath)) {
    Write-Error "Файл .env не найден в корне проекта: $envPath"
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
