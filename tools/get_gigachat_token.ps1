# Тест: OAuth токен GigaChat (значения из .env).
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

curl.exe -k -X POST "https://ngw.devices.sberbank.ru:9443/api/v2/oauth" `
  -H "Content-Type: application/x-www-form-urlencoded" `
  -H "Accept: application/json" `
  -H "RqUID: $rqUid" `
  -H "Authorization: Basic $authKey" `
  --data-urlencode "scope=$scope"
