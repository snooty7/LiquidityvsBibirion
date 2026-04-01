# Strategy Knowledge Base

## Current live recommendation
- Trade only `EURUSD`.
- Keep `per_trade_loss_guard_mode = position_risk`.
- Keep `per_trade_loss_risk_multiple = 1.0`.
- Use `confirmation_mode = sweep_displacement_mss`.
- Use `confirm_expiry_bars = 3`.
- Use `range_filter_max_compression_ratio = 2.5`.
- Use `range_filter_min_overlap_ratio = 0.75`.
- Use `confirmation_displacement_body_ratio_min = 0.60`.
- Use `confirmation_displacement_range_multiple = 1.80`.
- Keep base `order_block_max_distance_pips = 8.0`.
- Do not enable the conditional order-block override in live config yet.

## Why this is the current recommendation
### EURUSD M5 tuned candidate
Validated on 180-day backtest window `2025-09-29` to `2026-03-27`.

- Previous current candidate:
  - `disp = 1.70`
  - `overlap = 0.75`
  - trades: `85`
  - net: `+52.25`
  - PF: `1.269`
  - avg R: `0.142`
  - max DD: `$49.14`
- Improved candidate:
  - `disp = 1.80`
  - `overlap = 0.75`
  - trades: `76`
  - net: `+68.08`
  - PF: `1.405`
  - avg R: `0.208`
  - max DD: `$44.83`

Interpretation:
- Fewer trades, but cleaner trades.
- Better profit factor and expectancy.
- Slightly lower drawdown.
- This is a meaningful improvement, not just a trade-count artifact.

## Multi-symbol expansion results
All tests used the same strategy family on a 180-day window.

### Rejected symbols
- `GBPUSD`: net `-34.85`, PF `0.820`
- `USDJPY`: net `-5.29`, PF `0.943`
- `USDCAD`: net `-49.41`, PF `0.688`
- `AUDUSD`: net `-19.72`, PF `0.873`
- `NZDUSD`: net `-75.82`, PF `0.681`
- `USDCHF`: net `-38.75`, PF `0.872`

Interpretation:
- `EURUSD` remains the only symbol with a defendable edge in the current model.
- Do not add the other symbols to live trading with a copy-paste config.

## USDJPY branch research
A small dedicated `USDJPY` branch was tested with adjusted spread tolerance and nearby threshold tuning.

Best branch tested on 180 days:
- `sl_pips = 10`
- `confirmation_displacement_range_multiple = 1.70`
- `range_filter_min_overlap_ratio = 0.70`
- `max_spread_pips = 2.6`
- trades: `58`
- net: `+1.91`
- PF: `1.023`
- avg R: `0.012`
- max DD: `$23.18`

Interpretation:
- Technically no longer negative.
- Practically too weak to justify a live slot.
- Keep as a research branch only.

## EURUSD timeframe research
Exploratory 180-day comparison:

- `M5 current candidate`:
  - trades: `76`
  - net: `+68.08`
  - PF: `1.405`
  - avg R: `0.208`
- `M15 exploratory`:
  - trades: `49`
  - net: `-113.80`
  - PF: `0.450`
  - avg R: `-0.359`
- `M30 exploratory`:
  - trades: `12`
  - net: `+40.17`
  - PF: `2.164`
  - avg R: `0.388`

Interpretation:
- `M15` is rejected.
- `M30` is interesting, but the sample is too small (`12` trades in 180 days).
- `M30` should stay in research only until it is validated on a longer window.

## Order-block distance findings
Recent `SKIP_ORDER_BLOCK` cases were split into:
- `no local order block`
- `order block too far`

For the `too far` subgroup, the blocked outcomes were mixed.
A conditional override was implemented and tested historically.

Result:
- The override degraded both the 90-day and 180-day EURUSD results.
- Therefore the override must remain disabled in live config.

## Operational rules going forward
- Do not expand symbols unless a candidate is positive on at least 180 days with acceptable PF.
- Prefer improving `EURUSD` expectancy before adding breadth.
- Treat `USDJPY` and `EURUSD M30` as research branches, not production branches.
- Keep a strict separation between:
  - live config
  - historical experiment configs
  - research conclusions

## Useful report files
- `reports/eurusd_grid_90d.csv`
- `reports/eurusd_180d_validation.csv`
- `reports/eurusd_timeframe_compare_180d.csv`
- `reports/usdjpy_grid_90d.csv`
- `reports/usdjpy_180d_best_branch.csv`
- `reports/backtest_gbpusd_180d.csv`
- `reports/backtest_usdjpy_180d.csv`
- `reports/backtest_usdcad_180d.csv`
- `reports/backtest_audusd_180d.csv`
- `reports/backtest_nzdusd_180d.csv`
- `reports/backtest_usdchf_180d.csv`
