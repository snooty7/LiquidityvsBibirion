param(
  [string]$Config = "config/settings.json",
  [string]$Launcher = "live/start_all_16_live.ps1",
  [int]$MaxStaleMinutes = 20,
  [switch]$WeekdaysOnly = $true,
  [string]$SessionStart = "07:00",
  [string]$SessionEnd = "23:00"
)

$ErrorActionPreference = 'Stop'

$configPath = (Resolve-Path $Config).Path
$launcherPath = (Resolve-Path $Launcher).Path
$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$reportsDir = Join-Path $repoRoot 'reports'
if (-not (Test-Path $reportsDir)) {
  New-Item -ItemType Directory -Path $reportsDir | Out-Null
}
$healthLog = Join-Path $reportsDir 'live_healthcheck.log'

$configJson = Get-Content $configPath -Raw | ConvertFrom-Json
$botLogFile = [string]$configJson.runtime.log_file
if (-not [System.IO.Path]::IsPathRooted($botLogFile)) {
  $botLogFile = Join-Path $repoRoot $botLogFile
}

function Write-HealthLog {
  param([string]$Message)

  $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
  Add-Content -Path $healthLog -Value $line
  Write-Host $line
}

function Get-OrchestratorProcess {
  param(
    [string]$ResolvedConfigPath,
    [string]$RelativeConfigHint
  )

  Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'python.exe' -and
    $_.CommandLine -and
    $_.CommandLine -match 'src.engine.orchestrator' -and
    (
      $_.CommandLine -match [regex]::Escape($ResolvedConfigPath) -or
      $_.CommandLine -match [regex]::Escape($RelativeConfigHint)
    )
  } | Select-Object -First 1
}

$now = Get-Date
$dayName = $now.DayOfWeek
if ($WeekdaysOnly -and $dayName -in @('Saturday', 'Sunday')) {
  Write-HealthLog "skip weekend day=$dayName"
  exit 0
}

$startTime = [TimeSpan]::Parse($SessionStart)
$endTime = [TimeSpan]::Parse($SessionEnd)
$nowTime = $now.TimeOfDay
if ($nowTime -lt $startTime -or $nowTime -gt $endTime) {
  Write-HealthLog "skip outside_session now=$($now.ToString('HH:mm:ss')) session=$SessionStart-$SessionEnd"
  exit 0
}

$orchestrator = Get-OrchestratorProcess -ResolvedConfigPath $configPath -RelativeConfigHint $Config
$botLogInfo = $null
if (Test-Path $botLogFile) {
  $botLogInfo = Get-Item $botLogFile
}

$restartReason = ''
if (-not $orchestrator) {
  $restartReason = 'orchestrator_missing'
} elseif (-not $botLogInfo) {
  $restartReason = 'bot_log_missing'
} else {
  $staleMinutes = ($now - $botLogInfo.LastWriteTime).TotalMinutes
  if ($staleMinutes -gt $MaxStaleMinutes) {
    $restartReason = "bot_log_stale_${([int][math]::Round($staleMinutes))}m"
  }
}

if ($restartReason) {
  Write-HealthLog "restart reason=$restartReason launcher=$launcherPath"
  Start-Process powershell.exe -ArgumentList @(
    '-ExecutionPolicy',
    'Bypass',
    '-File',
    $launcherPath
  ) | Out-Null
  exit 0
}

Write-HealthLog "healthy pid=$($orchestrator.ProcessId) bot_log_ts=$($botLogInfo.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))"
