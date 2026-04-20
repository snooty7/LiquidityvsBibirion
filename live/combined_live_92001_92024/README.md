# Combined Monday Live Profile

Live profile for the current production branch plus the Monday expansion shortlist.

Branches:
- 92001 EURUSD M5 liquidity_sweep
- 92021 GBPUSD M1 trend_micro_burst_v2
- 92022 GBPUSD M1 NY tight
- 92023 NZDUSD M30 liquidity_sweep
- 92024 USDCHF M30 liquidity_sweep

News blackout:
- provider: investpy
- blocked importances: high, medium
- window: 30m before / 15m after

Run live:
`python -m src.engine.orchestrator --config live/combined_live_92001_92024/settings.json`
