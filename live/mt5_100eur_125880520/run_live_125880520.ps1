param(
  [string]$Config = "live/mt5_100eur_125880520/settings.json"
)

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo

$launcher = Join-Path $repo 'live\start_all_16_live.ps1'
powershell -ExecutionPolicy Bypass -File $launcher -Config $Config
