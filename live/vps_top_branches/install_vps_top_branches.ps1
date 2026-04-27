param(
  [string]$Config = "live/vps_top_branches/settings.json",
  [string]$Launcher = "live/vps_top_branches/start_vps_live.ps1",
  [string]$TaskPrefix = "MT5-VPS",
  [string]$StartTime = "07:00",
  [string]$HealthStartTime = "07:05",
  [string]$HealthEndTime = "23:05",
  [int]$HealthEveryHours = 1,
  [int]$MaxStaleMinutes = 20
)

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$installer = Join-Path $repo 'live\install_weekday_autostart_and_healthcheck.ps1'

powershell -ExecutionPolicy Bypass -File $installer `
  -Config $Config `
  -Launcher $Launcher `
  -StartTime $StartTime `
  -HealthStartTime $HealthStartTime `
  -HealthEndTime $HealthEndTime `
  -HealthEveryHours $HealthEveryHours `
  -MaxStaleMinutes $MaxStaleMinutes `
  -TaskPrefix $TaskPrefix
