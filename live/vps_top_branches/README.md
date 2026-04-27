# VPS Top Branches

This profile is a VPS-ready live set that keeps only the strongest recent branches.

Selected branches:
- `92015` `EURUSD M5`
- `92008` `EURUSD M30`
- `92014` `EURUSD M1`
- `92021` `GBPUSD M1`
- `92024` `USDCHF M30`

Selection basis:
- recent combined daily reviews from `2026-04-20` and `2026-04-21`
- positive net pips over the two-day aggregate
- enough sample size to avoid single-sample noise

Not included yet:
- `92017` was positive on one sample, but there is not enough history to justify live use yet.
- the negative branches from the mixed live set were excluded from this VPS profile.

Startup:
```powershell
powershell -ExecutionPolicy Bypass -File live\vps_top_branches\start_vps_live.ps1
```

Auto-start and healthcheck:
```powershell
powershell -ExecutionPolicy Bypass -File live\vps_top_branches\install_vps_top_branches.ps1
```

Runtime files are isolated inside this folder:
- `bot_state.sqlite3`
- `bot_events.csv`
- `news_calendar_cache.json`
