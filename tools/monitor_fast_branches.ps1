param(
  [string]$Config = "config/settings.json"
)

$ErrorActionPreference = 'Stop'

$configPath = Resolve-Path $Config
$configJson = Get-Content $configPath -Raw | ConvertFrom-Json
$logFile = $configJson.runtime.log_file
if (-not [System.IO.Path]::IsPathRooted($logFile)) {
  $repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
  $logFile = Join-Path $repoRoot $logFile
}

$magicMap = @{}
$symbolTfMap = @{}
foreach ($item in $configJson.symbols) {
  $label = "$($item.symbol) $($item.timeframe)"
  if ($item.magic) {
    $label = "$label magic=$($item.magic)"
    $magicMap[[string]$item.magic] = $label
  }
  $symbolTfMap["$($item.symbol),$($item.timeframe)"] = $label
}

Write-Host "MONITOR config=$configPath"
Write-Host "MONITOR log=$logFile"

while ($true) {
  Clear-Host
  Get-Date
  "config: $configPath"
  "log:    $logFile"
  ""

  if (-not (Test-Path $logFile)) {
    "log file not found yet"
    Start-Sleep -Seconds 5
    continue
  }

  Get-Content $logFile -Tail 400 |
    Select-String "LIQUIDITY_ALERT|SETUP_PENDING|SETUP_WAIT|SETUP_CONFIRMED|SKIP_SESSION|SKIP_NEWS|TRADE_OK|TRADE_FAIL|RISK_CLOSE_OK|POSITION_CLOSED_BROKER|POSITION_CLOSED_UNCONFIRMED|SCALP_" |
    ForEach-Object {
      $line = $_.Line
      $label = "OTHER"

      foreach ($magic in $magicMap.Keys) {
        if ($line -match "magic=$magic") {
          $label = $magicMap[$magic]
          break
        }
      }

      if ($label -eq "OTHER") {
        $parts = $line.Split(",")
        if ($parts.Length -ge 3) {
          $symbol = $parts[1]
          $timeframe = $parts[2]
          $key = "$symbol,$timeframe"
          if ($symbolTfMap.ContainsKey($key)) {
            $label = $symbolTfMap[$key]
          }
        }
      }

      "[{0}] {1}" -f $label, $line
    }

  Start-Sleep -Seconds 5
}
