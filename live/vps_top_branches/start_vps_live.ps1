param(
  [string]$Config = "live/vps_top_branches/settings.json"
)

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo

$launcher = Join-Path $repo 'live\start_all_16_live.ps1'
powershell -ExecutionPolicy Bypass -File $launcher -Config $Config
