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

## EURUSD trend micro-burst research
`Trend Micro-Burst v1` was tested as:
- `H4` trend context
- `M1` pullback + micro breakout entry
- fast exits via:
  - `1-2` adverse closes
  - or `1` large adverse `M1` bar

Test window:
- `2025-12-23` to `2026-03-31`

Best `London` cases:
- `SL=4`, `RR=2`, `pullback=2`, `2 adverse closes`
  - trades: `579`
  - net: `-0.49`
  - PF: `0.994`
  - avg R: `-0.001`
- `SL=4`, `RR=2`, `pullback=3`, `2 adverse closes`
  - trades: `597`
  - net: `-0.61`
  - PF: `0.993`
  - avg R: `-0.001`

Best `New York` case:
- trades: `674`
- net: `-7.18`
- PF: `0.945`
- avg R: `-0.015`

Interpretation:
- The branch generates the desired trade frequency.
- `London` is close to breakeven.
- `New York` is not acceptable.
- `v1` is not good enough for live deployment.
- The problem is no longer signal scarcity; the problem is expectancy.

Decision:
- Mark `Trend Micro-Burst v1` as `rejected-for-live / near-breakeven`.
- Do not add it to demo or production as-is.
- Continue only with a `London-only v2` branch and a different exit architecture.

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

## Future Branch Roadmap
### 1. `eurusd_m30_liquidity_branch`
Status:
- Enabled locally in demo as a low-risk secondary branch.
- Still under-validated because the usable historical sample is small.

Purpose:
- Capture slower, cleaner liquidity/structure moves than `EURUSD M5`.
- Accept lower trade frequency in exchange for potentially higher per-trade quality.

Current profile:
- `timeframe = M30`
- `bias_timeframe = H1`
- `confirmation timeframe = M5`
- `sl_pips = 20`
- `risk_pct = 0.05`
- `max_lot = 0.03`

Decision rule:
- Keep it live only on demo until meaningful sample size is collected.
- Do not promote it to the primary branch yet.

### 2. `usdjpy_liquidity_branch`
Status:
- Research only.

Purpose:
- Explore whether a JPY-specific liquidity model can become a second production branch.

Current evidence:
- Best tested branch is roughly flat, not convincingly profitable.
- It is not ready for live deployment.

Next research direction:
- Separate thresholds from `EURUSD`.
- Focus on spread handling, session timing, and confirmation strength.

### 3. `session_open_scalp_branch`
Status:
- Design stage only.

Purpose:
- Add a high-frequency, session-driven branch that still respects the core liquidity philosophy.
- This branch must not become an indicator-noise bot.

Core idea:
- Opening range liquidity event
- Followed by `C1`-style micro confirmation
- Fast management, fast invalidation, and session-bound exits

Research requirement:
- Build and backtest it as a separate branch, not as a patch on the current `M5` liquidity model.

### 4. `trend_micro_burst_v2_branch`
Status:
- Specification only.

Purpose:
- Build a fast, trend-following micro branch with many trades, but without falling into `next pip` noise.
- Keep the model aligned with the current philosophy:
  - higher-timeframe context
  - lower-timeframe trigger
  - fast invalidation

What was learned from `v1`:
- H4 context is useful.
- Fixed-RR exits are too rigid for this branch.
- London session is materially better than New York.

Research direction:
- `London-only`
- `H4` trend filter
- `M1` breakout-pullback-reacceleration entry
- no symmetric fixed-RR as the primary exit
- favor:
  - quick partial
  - fail-fast momentum exit
  - trend-decay exit

Preliminary implementation result:
- `London-only` does show a positive pocket.
- Best tested `v2` case so far:
  - `pullback_bars = 3`
  - `body_ratio = 0.45`
  - `range_multiple = 1.4`
  - `SL = 4 pips`
  - `RR = 1.5`
  - `2 adverse closes`
  - `large_adverse_body_r = 0.6`
  - trades: `114`
  - net: `+4.61`
  - PF: `1.352`
  - avg R: `0.058`
  - max DD: `$3.50`

Interpretation:
- Better than `v1`.
- Still modest, but now positive and testable.
- This is a research candidate for demo, not a production branch yet.

