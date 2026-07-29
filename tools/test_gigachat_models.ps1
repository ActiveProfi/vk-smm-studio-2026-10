# Тест: список моделей GigaChat.
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }

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

$authKey = $envMap["GIGACHAT_AUTH_KEY"]
$scope = $envMap["GIGACHAT_SCOPE"]

if (-not $authKey) { Write-Error "В .env пустая строка GIGACHAT_AUTH_KEY."; exit 1 }
if (-not $scope) { Write-Error "В .env пустая строка GIGACHAT_SCOPE."; exit 1 }

$rqUid = [guid]::NewGuid().Guid

$tokenResponse = Invoke-RestMethod `
  -Method Post `
  -Uri "https://ngw.devices.sberbank.ru:9443/api/v2/oauth" `
  -Headers @{
    "Accept" = "application/json"
    "RqUID" = $rqUid
    "Authorization" = "Basic $authKey"
  } `
  -ContentType "application/x-www-form-urlencoded" `
  -Body "scope=$scope"

$accessToken = $tokenResponse.access_token
if (-not $accessToken) { Write-Error "Не удалось получить access_token."; exit 1 }

$modelsResponse = curl.exe -k "https://gigachat.devices.sberbank.ru/api/v1/models" `
  -H "Accept: application/json" `
  -H "Authorization: Bearer $accessToken"

$modelsResponse
