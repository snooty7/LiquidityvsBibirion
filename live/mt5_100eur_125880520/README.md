# Live Profile: 100 EUR / Account 125880520

This profile is isolated for the live account:
- `125880520`
- `MT5 STANDARD EUR`
- account currency: `EUR`

Active branches:
- `92015` `EURUSD M5`
- `92008` `EURUSD M30`
- `92014` `EURUSD M1`
- `92021` `GBPUSD M1`
- `92024` `USDCHF M30`

Risk posture:
- `max_open_positions_total = 1`
- `daily_loss_limit_usd = 5.0`
- `max_loss_per_trade_usd = 2.0`
- `max_lot = 0.01` on all branches

Practical interpretation:
- with a 100 EUR account, this keeps the bot at the broker minimum lot size
- actual per-trade risk is still driven by stop distance
- the M30 branches are the heaviest risk-wise, so keep them at 0.01 lot only

News filter:
- enabled
- blocks high/medium impact events
- timezone: `Europe/Sofia`

Start:
```powershell
powershell -ExecutionPolicy Bypass -File live\mt5_100eur_125880520\run_live_125880520.ps1
```

Before start:
1. Log MT5 into account `125880520`
2. Make sure the terminal is the active one you want the bot to trade on
3. Keep only one bot profile attached to that terminal

Notes:
- This profile is intentionally conservative for a 100 EUR live trial.
- If the broker allows sub-0.01 volume in the future, the risk can be tightened further.
