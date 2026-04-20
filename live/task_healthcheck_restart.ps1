$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
powershell -ExecutionPolicy Bypass -File (Join-Path $repo 'tools\live_healthcheck_restart.ps1')
