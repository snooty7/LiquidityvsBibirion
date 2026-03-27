while ($true) {
  Clear-Host
  Get-Date
  ""
  Select-String -Path bot_events.csv -Pattern "SETUP_PENDING|SETUP_CONFIRMED|TRADE_OK|TRADE_FAIL|TRAILING_STOP_OK|TRAILING_STOP_FAIL|RISK_CLOSE_OK|RISK_CLOSE_FAIL" |
    Select-Object -Last 20 |
    ForEach-Object { $_.Line }
  Start-Sleep -Seconds 5
}
