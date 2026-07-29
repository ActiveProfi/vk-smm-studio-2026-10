# Безопасная проверка VK API: ничего не публикует.
# Проверяет, что токен сообщества и ID группы читаются из .env.

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

$token = $envMap["VK_COMMUNITY_TOKEN"]
$groupId = $envMap["VK_GROUP_ID"]
$apiVersion = $envMap["VK_API_VERSION"]

if (-not $token) { Write-Error "В .env пустая строка VK_COMMUNITY_TOKEN."; exit 1 }
if (-not $groupId) { Write-Error "В .env пустая строка VK_GROUP_ID."; exit 1 }
if (-not $apiVersion) { $apiVersion = "5.199" }

$uri = "https://api.vk.com/method/groups.getById?group_id=$groupId&access_token=$token&v=$apiVersion"
$response = Invoke-RestMethod -Method Get -Uri $uri
$response | ConvertTo-Json -Depth 6
