param(
  [string]$Config = "config/settings.json",
  [string]$Launcher = "live/start_all_16_live.ps1",
  [int]$StaleSeconds = 90,
  [int]$CheckSeconds = 15,
  [int]$RestartCooldownSeconds = 180
)

$ErrorActionPreference = 'Stop'

$configPath = (Resolve-Path $Config).Path
$launcherPath = (Resolve-Path $Launcher).Path
$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$configJson = Get-Content $configPath -Raw | ConvertFrom-Json
$logFile = [string]$configJson.runtime.log_file
if (-not [System.IO.Path]::IsPathRooted($logFile)) {
  $logFile = Join-Path $repoRoot $logFile
}

$lastRestartAt = [datetime]::MinValue

function Get-OrchestratorProcess {
  param([string[]]$ConfigArgs)

  Get-CimInstance Win32_Process | Where-Object {
    $cmd = $_.CommandLine
    if (-not $cmd) {
      return $false
    }
    if ($_.Name -ne 'python.exe') {
      return $false
    }
    if ($cmd -notmatch 'src.engine.orchestrator') {
      return $false
    }
    foreach ($configArg in $ConfigArgs) {
      if ($configArg -and $cmd -match [regex]::Escape($configArg)) {
        return $true
      }
    }
    return $false
  } | Select-Object -First 1
}

Write-Host "WATCHDOG config=$configPath"
Write-Host "WATCHDOG launcher=$launcherPath"
Write-Host "WATCHDOG log=$logFile stale=${StaleSeconds}s check=${CheckSeconds}s cooldown=${RestartCooldownSeconds}s"

while ($true) {
  $now = Get-Date
  $orchestrator = Get-OrchestratorProcess -ConfigArgs @($Config, $configPath)
  $logInfo = $null
  if (Test-Path $logFile) {
    $logInfo = Get-Item $logFile
  }

  $shouldRestart = $false
  $reason = ''

  if (-not $orchestrator) {
    $shouldRestart = $true
    $reason = 'orchestrator_missing'
  } elseif (-not $logInfo) {
    $shouldRestart = $true
    $reason = 'log_missing'
  } else {
    $ageSeconds = ($now - $logInfo.LastWriteTime).TotalSeconds
    if ($ageSeconds -gt $StaleSeconds) {
      $shouldRestart = $true
      $reason = "log_stale_${([int][math]::Round($ageSeconds))}s"
    }
  }

  if ($shouldRestart) {
    $cooldownAge = ($now - $lastRestartAt).TotalSeconds
    if ($cooldownAge -ge $RestartCooldownSeconds) {
      $lastRestartAt = $now
      Write-Host "WATCHDOG restart reason=$reason at=$($now.ToString('s'))"
      Start-Process powershell -ArgumentList @(
        '-NoExit',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        $launcherPath
      ) | Out-Null
      Start-Sleep -Seconds 10
    }
  }

  Start-Sleep -Seconds $CheckSeconds
}
