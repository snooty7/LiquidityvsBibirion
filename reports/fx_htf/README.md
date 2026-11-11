# FX H1/H4: trend pullback and confirmed range breakout

**Highest descriptive new-model net: USDCHF / `htf_range_retest`, EUR -17.52.**

**Neither new fixed model produced positive full-period net on any of the three pairs.**

All profits below are after modeled spread, commission and slippage. **Swap/overnight financing is not included.** Overnight trade counts are disclosed. Results are research-only, with no live deployment approval. Historical dates were previously examined and are not untouched future data.

Overnight counts flag changes of UTC calendar date; they are not exact broker rollover counts.

Each pair/model is an independent EUR 10,000 simulation. Do not add these returns into a single EUR 10,000 account or infer a combined portfolio result.

## All nine independent accounts: twelve test windows

| Pair | Model | Trades | Net EUR | Return | PF | Realized DD EUR | Overnight trades |
|---|---|---:|---:|---:|---:|---:|---:|
| USDCHF | baseline | 143 | 147.86 | 1.479% | 1.231 | 69.87 | 65 |
| EURUSD | baseline | 148 | 6.03 | 0.060% | 1.009 | 189.27 | 47 |
| USDCHF | htf_range_retest | 8 | -17.52 | -0.175% | 0.519 | 33.15 | 3 |
| EURUSD | htf_range_retest | 11 | -20.53 | -0.205% | 0.574 | 20.53 | 4 |
| GBPUSD | htf_trend_pullback | 75 | -30.40 | -0.304% | 0.920 | 69.47 | 21 |
| GBPUSD | htf_range_retest | 14 | -63.40 | -0.634% | 0.336 | 65.27 | 1 |
| EURUSD | htf_trend_pullback | 62 | -72.54 | -0.725% | 0.755 | 123.17 | 21 |
| USDCHF | htf_trend_pullback | 62 | -77.19 | -0.772% | 0.744 | 103.41 | 25 |
| GBPUSD | baseline | 167 | -122.23 | -1.222% | 0.859 | 203.58 | 26 |

## Later-six confirmation subset and doubled commission/slippage

| Pair | Model | Trades | Confirmation net EUR | Stressed net EUR | Stressed realized DD EUR |
|---|---|---:|---:|---:|---:|
| USDCHF | baseline | 62 | 93.87 | 66.33 | 48.04 |
| EURUSD | baseline | 80 | 2.42 | -39.91 | 166.62 |
| USDCHF | htf_range_retest | 3 | -4.61 | -6.05 | 9.85 |
| EURUSD | htf_range_retest | 3 | -16.96 | -18.64 | 18.64 |
| GBPUSD | htf_trend_pullback | 41 | 17.47 | -5.98 | 84.83 |
| GBPUSD | htf_range_retest | 7 | -22.28 | -26.26 | 27.15 |
| EURUSD | htf_trend_pullback | 31 | -43.17 | -60.96 | 98.92 |
| USDCHF | htf_trend_pullback | 31 | -24.44 | -48.45 | 89.30 |
| GBPUSD | baseline | 85 | -22.36 | -70.95 | 124.30 |

## Cost reconciliation: full test period

| Pair | Model | Gross EUR | Spread EUR | Commission EUR | Slippage EUR | Net EUR |
|---|---|---:|---:|---:|---:|---:|
| USDCHF | baseline | 279.56 | 66.89 | 40.04 | 24.77 | 147.86 |
| EURUSD | baseline | 101.14 | 16.63 | 51.80 | 26.68 | 6.03 |
| USDCHF | htf_range_retest | -11.26 | 2.64 | 2.24 | 1.39 | -17.52 |
| EURUSD | htf_range_retest | -13.66 | 1.04 | 3.85 | 1.98 | -20.53 |
| GBPUSD | htf_trend_pullback | 19.74 | 10.37 | 26.25 | 13.52 | -30.40 |
| GBPUSD | htf_range_retest | -55.26 | 0.72 | 4.90 | 2.52 | -63.40 |
| EURUSD | htf_trend_pullback | -33.44 | 6.22 | 21.70 | 11.18 | -72.54 |
| USDCHF | htf_trend_pullback | -24.51 | 24.59 | 17.36 | 10.74 | -77.19 |
| GBPUSD | baseline | -12.71 | 20.96 | 58.45 | 30.11 | -122.23 |

## Frozen training nominations

Fixed nominations use only the first six prior training windows. Their full-period results include development overlap; the later six windows are the within-study confirmation subset. Neither test-period winners nor later training windows can change the fixed nomination.

| Pair | Fixed choice | Declared historical gates | Failed gates |
|---|---|---|---|
| EURUSD | baseline | FAIL | alternative_selected_from_training; aggregate_net_improved; holdout_net_positive_and_improved; stress_net_positive_and_not_worse |
| GBPUSD | baseline | FAIL | alternative_selected_from_training; aggregate_net_improved; holdout_net_positive_and_improved; stress_net_positive_and_not_worse |
| USDCHF | baseline | FAIL | alternative_selected_from_training; aggregate_net_improved; holdout_net_positive_and_improved |

A historical gate pass is not live approval: financing assumptions, fresh forward evidence and execution fidelity still require validation.

| Pair | Candidate | Training net sum EUR | Training DD sum EUR | Windows >=20 trades | Rejection reasons |
|---|---|---:|---:|---:|---|
| EURUSD | htf_trend_pullback | -75.04 | 389.98 | 6/6 | development-training net sum not positive and improved |
| EURUSD | htf_range_retest | -140.45 | 217.83 | 0/6 | fewer than four development-training windows with 20 trades; development-training net sum not positive and improved |
| GBPUSD | htf_trend_pullback | -0.34 | 703.20 | 6/6 | development-training net sum not positive and improved |
| GBPUSD | htf_range_retest | -235.47 | 363.48 | 0/6 | fewer than four development-training windows with 20 trades; development-training net sum not positive and improved |
| USDCHF | htf_trend_pullback | -527.19 | 753.35 | 6/6 | development-training net sum not positive and improved |
| USDCHF | htf_range_retest | 19.02 | 168.53 | 0/6 | fewer than four development-training windows with 20 trades |

Training windows overlap; these sums are selection diagnostics, not independent account returns.

## Adaptive training-selected policies

These choose separately for each window using only its prior training data. Their results do not override fixed-profile promotion gates.

| Pair | Full-period net EUR | Confirmation net EUR | Stressed confirmation net EUR |
|---|---:|---:|---:|
| EURUSD | 16.42 | 18.59 | -24.17 |
| GBPUSD | -36.54 | 101.57 | 70.76 |
| USDCHF | 147.86 | 93.87 | 66.33 |

## Cross-market descriptive check

| New model | Pairs positive over full tests | Pairs beating own baseline | Pairs positive under confirmation stress |
|---|---:|---:|---:|
| htf_trend_pullback | 0/3 | 1/3 | 0/3 |
| htf_range_retest | 0/3 | 1/3 | 0/3 |

## Frozen rules and protocol

- `htf_trend_pullback`: H4 EMA20 above/below EMA50 with EMA50 slope over three bars; aligned H1 EMA20/50, previous H1 close pulls back across EMA20, current directional >=50%-body candle reclaims EMA20 and breaks previous high/low by 0.3 pip.
- `htf_range_retest`: Same H4 trend; previous H1 closes beyond the prior 20-bar range by 0.3 pip; current H1 retests that boundary and closes outside it with a directional >=50%-body candle. Range excludes breakout and confirmation bars.
- Common reference: original USDCHF M30/M1 liquidity model applied separately to each pair with identical risk settings; not the previously configured EURUSD/GBPUSD live branches.
- Fixed 150 closed H1/H4 bars (3*EMA50); no forming candles; H4 must close by H1 decision.
- 0.1% planned risk, 20-pip initial stop, 0.05 maximum lot, 2R initial TP, original 1R/1R trailing, same daily loss/exposure/valuation guards, one position per symbol, one-hour cooldown and original entry sessions/spread cap. No risk override, averaging or stop widening.
- Twelve nonoverlapping 30-day tests: 16 November 2025 through 10 November 2026 UTC. Each uses 365 preceding training days and a one-day embargo. First six prior training windows nominate the fixed model; last six test windows are the confirmation subset.
- Every training and test window passed native history/indicator warm-up coverage checks before registration. Warm-up retrieval includes a calendar-week allowance for year-end holidays; missing bars are never fabricated.
- Thresholds/parameters fixed before replay; one setting per new model, no tuning grid. All pairs' training choices locked before any test replay.
- Base execution: historical spread; EUR 3.50/lot/side assumed commission, 0.2-pip adverse market/stop slippage. Stress doubles commission/slippage to EUR 7.00 and 0.4 pip. Historical spread is unchanged; missing-spread fallback doubles from 1 to 2 pips.
- EURUSD/GBPUSD extended read-only from an already-running connected MT5 terminal with AutoTrading disabled; USDCHF uses the prior read-only snapshot. No bot/order operations.
- These dates and prior strategies were examined before. Outcomes for these two new models are evaluated after registration; the historical period is not genuinely untouched future data.
- Three independently simulated EUR 10,000 accounts per model; no combined portfolio/correlation or concurrent cross-symbol daily/exposure simulation. Returns cannot be added into a single-account return.
- Folds start flat monthly; no compounding. Training windows overlap; their sums are selection diagnostics. Drawdown is realized cash-flow drawdown, not intratrade equity drawdown.
- Commission and slippage are assumptions; historical symbol valuation is constant. Swap/overnight financing, latency and full tick paths are not modeled. Overnight-trade counts are disclosed; net is after modeled execution costs, not every possible broker charge.
- Monthly forced closes limit holding duration. Multiple comparisons and prior history reuse limit inference; no model is approved for real-money trading by descriptive profit alone.
- Saved-history replay explicitly blocks MT5 initialization and trading methods. No bot started, no orders placed, no active settings modified.

## Reproduction and independent audit

```powershell
.\.venv\Scripts\python.exe -m src.tools.research_fx_htf --workers 4
.\.venv\Scripts\python.exe -m src.tools.render_fx_htf reports/fx_htf/report.json
```

`plan.json` records source/data hashes, valuation snapshots and all settings. `locked_selections.json` holds prior-training evidence and choices. `report.json` has all 270 train/test/stress rows. `test_trades.json` exposes every test trade and its modeled costs. `audit.json` verifies completeness and independently reconstructs all 162 test/stress rows and account summaries, including boundaries, commission, lot caps and stop monotonicity.
