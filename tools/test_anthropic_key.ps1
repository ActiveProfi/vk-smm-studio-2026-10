# Тест: краткий запрос в Anthropic API (Claude).
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

$apiKey = $envMap["ANTHROPIC_API_KEY"]
if (-not $apiKey) { Write-Error "В .env пустая строка ANTHROPIC_API_KEY."; exit 1 }

$body = @{
    model     = "claude-3-5-haiku-20241022"
    max_tokens = 50
    messages  = @(
        @{
            role    = "user"
            content = @(
                @{ type = "text"; text = "Ответь одним словом: ok" }
            )
        }
    )
} | ConvertTo-Json -Depth 8 -Compress

curl.exe "https://api.anthropic.com/v1/messages" `
  -H "x-api-key: $apiKey" `
  -H "anthropic-version: 2023-06-01" `
  -H "content-type: application/json" `
  -d $body
