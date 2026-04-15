$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$config = 'config/settings.json'
$monitor = Join-Path $repo 'tools\monitor_fast_branches.ps1'
$configResolved = (Resolve-Path $config).Path
$monitorResolved = (Resolve-Path $monitor).Path
$launcherResolved = (Resolve-Path $MyInvocation.MyCommand.Path).Path

function Stop-ExistingLiveProcesses {
    param(
        [string]$ConfigPath,
        [string]$MonitorPath,
        [string]$LauncherPath
    )

    $currentPid = $PID
    $processes = Get-CimInstance Win32_Process | Where-Object {
        $_.ProcessId -ne $currentPid -and $_.CommandLine
    }

    $pythonTargets = $processes | Where-Object {
        $_.Name -eq 'python.exe' -and (
            $_.CommandLine -match [regex]::Escape('--config') -and
            $_.CommandLine -match [regex]::Escape('config/settings.json')
        )
    }

    $shellTargets = $processes | Where-Object {
        $_.Name -eq 'powershell.exe' -and (
            $_.CommandLine -match [regex]::Escape($MonitorPath) -or
            $_.CommandLine -match [regex]::Escape($LauncherPath)
        )
    }

    $targets = @()
    if ($pythonTargets) {
        $targets += @($pythonTargets)
    }
    if ($shellTargets) {
        $targets += @($shellTargets)
    }

    foreach ($proc in $targets | Sort-Object ProcessId -Unique) {
        try {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
        } catch {
            Write-Host "WARN failed to stop pid=$($proc.ProcessId): $($_.Exception.Message)"
        }
    }

    Start-Sleep -Seconds 2
}

Stop-ExistingLiveProcesses -ConfigPath $configResolved -MonitorPath $monitorResolved -LauncherPath $launcherResolved

Start-Process powershell -ArgumentList @('-NoExit','-ExecutionPolicy','Bypass','-File', $monitor, '-Config', $config) | Out-Null
python -m src.engine.orchestrator --config $config
