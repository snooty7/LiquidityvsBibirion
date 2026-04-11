$magicMap = @{
  "92009" = "EURUSD M1 London Scalp"
  "92010" = "EURUSD M1 NY Scalp"
  "92011" = "GBPUSD M1 London Scalp"
  "92012" = "GBPUSD M1 NY Scalp"
  "92013" = "USDJPY M1 London Scalp"
  "92014" = "EURUSD M1 Trend Micro-Burst v2"
  "92016" = "EURUSD M1 NY ORB v2"
  "92021" = "GBPUSD M1 Trend Micro-Burst v2"
  "92022" = "GBPUSD M1 NY Tight"
  "92023" = "NZDUSD M30 Sweep"
  "92024" = "USDCHF M30 Sweep"
}

while ($true) {
  Clear-Host
  Get-Date
  ""
  Get-Content bot_events.csv -Tail 400 |
    Select-String "LIQUIDITY_ALERT|SETUP_PENDING|SETUP_WAIT|SETUP_CONFIRMED|SKIP_SESSION|TRADE_OK|TRADE_FAIL|RISK_CLOSE_OK|POSITION_CLOSED_BROKER|POSITION_CLOSED_UNCONFIRMED|SCALP_" |
    ForEach-Object {
      $line = $_.Line
      $label = "OTHER"
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
