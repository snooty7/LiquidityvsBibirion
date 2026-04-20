$magicMap = @{
  "92001" = "EURUSD M5"
  "92008" = "EURUSD M30"
  "92009" = "EURUSD M1 London"
  "92010" = "EURUSD M1 New York"
  "92011" = "GBPUSD M1 London"
  "92012" = "GBPUSD M1 New York"
  "92013" = "USDJPY M1 London"
}

while ($true) {
  Clear-Host
  Get-Date
  ""
  Get-Content bot_events.csv -Tail 200 |
    Select-String "TRADE_OK|TRADE_FAIL|RISK_CLOSE_OK|RISK_CLOSE_FAIL|POSITION_CLOSED_BROKER|POSITION_CLOSED_UNCONFIRMED|TRAILING_STOP_OK|SETUP_CONFIRMED" |
    ForEach-Object {
      $line = $_.Line
      $label = "UNKNOWN"
      foreach ($magic in $magicMap.Keys) {
        if ($line -match "magic=$magic") {
          $label = $magicMap[$magic]
          break
        }
      }
      "[{0}] {1}" -f $label, $line
    }
  Start-Sleep -Seconds 5
}
