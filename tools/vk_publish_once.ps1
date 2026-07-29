$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$logDir = Join-Path $projectRoot "output\logs"
$logPath = Join-Path $logDir "vk-publisher.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Set-Location $projectRoot

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $logPath -Value ""
Add-Content -Path $logPath -Value "===== $stamp ====="

py -3 ".\publish_vk_scheduled.py" 2>&1 | Tee-Object -FilePath $logPath -Append
