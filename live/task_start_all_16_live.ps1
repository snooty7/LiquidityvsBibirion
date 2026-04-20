$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
powershell -ExecutionPolicy Bypass -File (Join-Path $repo 'live\start_all_16_live.ps1')
