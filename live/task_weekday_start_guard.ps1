$ErrorActionPreference = 'Stop'

$today = (Get-Date).DayOfWeek
if ($today -in @('Saturday', 'Sunday')) {
  Write-Host "skip weekend day=$today"
  exit 0
}

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
powershell -ExecutionPolicy Bypass -File (Join-Path $repo 'live\start_all_16_live.ps1')
