param(
  [string]$StartTime = "07:00",
  [string]$HealthStartTime = "07:05",
  [string]$HealthEndTime = "23:05",
  [int]$HealthEveryHours = 1,
  [int]$MaxStaleMinutes = 20,
  [string]$TaskPrefix = "MT5-Bot"
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$startScript = (Resolve-Path (Join-Path $repoRoot 'live\start_all_16_live.ps1')).Path
$healthScript = (Resolve-Path (Join-Path $repoRoot 'tools\live_healthcheck_restart.ps1')).Path
$configPath = (Resolve-Path (Join-Path $repoRoot 'config\settings.json')).Path
$reportsDir = Join-Path $repoRoot 'reports'
if (-not (Test-Path $reportsDir)) {
  New-Item -ItemType Directory -Path $reportsDir | Out-Null
}

$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$today = Get-Date
$startBoundary = (Get-Date "$($today.ToString('yyyy-MM-dd')) $StartTime").ToString("s")
$healthBoundary = (Get-Date "$($today.ToString('yyyy-MM-dd')) $HealthStartTime").ToString("s")
$healthStart = [TimeSpan]::Parse($HealthStartTime)
$healthEnd = [TimeSpan]::Parse($HealthEndTime)
$durationHours = [int][Math]::Ceiling(($healthEnd - $healthStart).TotalHours)
if ($durationHours -lt 1) {
  throw "HealthEndTime must be later than HealthStartTime."
}

$startTaskName = "$TaskPrefix Weekday Start 07:00"
$healthTaskName = "$TaskPrefix Hourly Health Check"

function New-TaskXml {
  param(
    [string]$UserId,
    [string]$StartBoundary,
    [string]$Command,
    [string]$Arguments,
    [string]$WorkingDirectory,
    [bool]$WakeToRun,
    [switch]$WeekdaysOnly,
    [string]$RepetitionInterval = "",
    [string]$RepetitionDuration = ""
  )

  $daysXml = ""
  if ($WeekdaysOnly) {
    $daysXml = @"
          <DaysOfWeek>
            <Monday />
            <Tuesday />
            <Wednesday />
            <Thursday />
            <Friday />
          </DaysOfWeek>
"@
  }

  $scheduleXml = if ($WeekdaysOnly) {
@"
        <ScheduleByWeek>
$daysXml
          <WeeksInterval>1</WeeksInterval>
        </ScheduleByWeek>
"@
  } else {
@"
        <ScheduleByDay>
          <DaysInterval>1</DaysInterval>
        </ScheduleByDay>
"@
  }

  $repetitionXml = ""
  if ($RepetitionInterval -and $RepetitionDuration) {
    $repetitionXml = @"
        <Repetition>
          <Interval>$RepetitionInterval</Interval>
          <Duration>$RepetitionDuration</Duration>
          <StopAtDurationEnd>false</StopAtDurationEnd>
        </Repetition>
"@
  }

@"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>$UserId</Author>
    <Description>Auto-generated MT5 bot task</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>$StartBoundary</StartBoundary>
      <Enabled>true</Enabled>
$repetitionXml
$scheduleXml
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$UserId</UserId>
      <LogonType>S4U</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>$($WakeToRun.ToString().ToLower())</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$Command</Command>
      <Arguments>$Arguments</Arguments>
      <WorkingDirectory>$WorkingDirectory</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@
}

$startArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`""
$healthArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$healthScript`" -Config `"$configPath`" -Launcher `"$startScript`" -MaxStaleMinutes $MaxStaleMinutes -WeekdaysOnly"

$startXml = New-TaskXml `
  -UserId $userId `
  -StartBoundary $startBoundary `
  -Command "powershell.exe" `
  -Arguments $startArgs `
  -WorkingDirectory $repoRoot `
  -WakeToRun $true `
  -WeekdaysOnly

$healthXml = New-TaskXml `
  -UserId $userId `
  -StartBoundary $healthBoundary `
  -Command "powershell.exe" `
  -Arguments $healthArgs `
  -WorkingDirectory $repoRoot `
  -WakeToRun $false `
  -RepetitionInterval ("PT{0}H" -f [int]$HealthEveryHours) `
  -RepetitionDuration ("PT{0}H" -f $durationHours)

Register-ScheduledTask -TaskName $startTaskName -Xml $startXml -Force | Out-Null
Register-ScheduledTask -TaskName $healthTaskName -Xml $healthXml -Force | Out-Null

Write-Host "Registered task: $startTaskName"
Write-Host "Registered task: $healthTaskName"
Write-Host "Start script: $startScript"
Write-Host "Health script: $healthScript"
Write-Host ""
Write-Host "Important:"
Write-Host "- WakeToRun can wake the PC from sleep/hibernate if Windows wake timers are allowed."
Write-Host "- Full power-on from shutdown requires BIOS/UEFI RTC wake or similar motherboard feature."
