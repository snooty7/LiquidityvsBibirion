param(
  [string]$Config = "config/settings.json",
  [string]$Launcher = "live/start_all_16_live.ps1"
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
powershell -ExecutionPolicy Bypass -File (Join-Path $repo $Launcher) -Config $Config
