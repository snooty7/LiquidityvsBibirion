# MT5 cost-aware walk-forward results

Completed on 11 November 2026 using saved broker history and offline replay. No bot was started and no trading methods were called.

**Main finding:** the training-selected available-instrument track returned **EUR -50.42 net** across 134 simulated trades after costs. The best individual profile in hindsight was USDCHF M30 at EUR +147.86 (143 trades, PF 1.231). This hindsight ranking is distinct from the training-only selection result.

- 30 existing branch profiles requested; 29 evaluated across all 12 test folds.
- BTCUSD is unavailable from this broker. BTCUSDT was evaluated separately; no instrument was substituted.
- 696 successful train/test windows; 24 unavailable BTCUSD windows; zero replay errors.
- Each fold uses 90 training days, a one-day embargo, and 30 test days. Tests do not overlap.
- Training starts 17 August 2025; test windows cover 16 November 2025 through 10 November 2026, UTC.
- Each profile/fold starts flat with EUR 10,000. Aggregate results sum independent folds; they are not a compounded live portfolio.

## Execution assumptions

Historical MT5 spreads are applied to bid/ask execution, with a 1.0-pip fallback only when spread is missing. Commission is assumed at EUR 3.50 per lot per side; market/stop slippage is assumed at 0.2 pip per execution. These are research assumptions, not verified broker fees. Take-profit limits do not receive adverse slippage; stop gaps use the worse opening quote.

Native broker timeframes were retained. A four-day history-gap tolerance explicitly accommodates the recorded Easter closure of three days and six minutes; no missing bars were filled.

## Out-of-sample comparison

This is a descriptive ranking of existing profiles, not a deployment recommendation. Native risk settings differ. Selection results based only on prior training follow below.

| Profile | Strategy / TF | Risk % | Trades | Gross EUR | Costs EUR | Net EUR | PF | Avg R | Realized DD EUR |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 92024-USDCHF-M30-3c27c3d9 | liquidity_sweep / M30 | 0.1 | 143 | 279.56 | 131.70 | 147.86 | 1.231 | 0.118 | 69.87 |
| 92024-USDCHF-M30-588bab2f | liquidity_sweep / M30 | 0.1 | 143 | 279.56 | 131.70 | 147.86 | 1.231 | 0.118 | 69.87 |
| 92024-USDCHF-M30-3562b843 | liquidity_sweep / M30 | 1.75 | 143 | 69.89 | 32.92 | 36.97 | 1.231 | 0.118 | 17.47 |
| 92008-EURUSD-M30-024e6fa9 | liquidity_sweep / M30 | 0.1 | 148 | 101.11 | 95.10 | 6.01 | 1.009 | 0.004 | 189.22 |
| 92025-EURUSD-M5-afb9c4e5 | volume_sweep_reclaim / M5 | 0.05 | 20 | 3.78 | 2.08 | 1.71 | 1.447 | 0.094 | 1.59 |
| 92008-EURUSD-M30-86ec1d4a | liquidity_sweep / M30 | 1.75 | 148 | 20.22 | 19.02 | 1.20 | 1.009 | 0.004 | 37.84 |
| 92022-GBPUSD-M1-f2b0002c | session_open_scalp / M1 | 0.02 | 25 | 11.14 | 10.68 | 0.46 | 1.014 | 0.010 | 9.85 |
| 92022-GBPUSD-M1-f5d7824c | session_open_scalp / M1 | 0.02 | 25 | 11.14 | 10.68 | 0.46 | 1.014 | 0.010 | 9.85 |
| 92008-EURUSD-M30-b99d210c | liquidity_sweep / M30 | 0.1 | 0 | 0.00 | 0.00 | 0.00 | n/a | 0.000 | 0.00 |
| 92014-EURUSD-M1-7fc699e6 | trend_micro_burst_v2 / M1 | 0.02 | 0 | 0.00 | 0.00 | 0.00 | n/a | 0.000 | 0.00 |
| 92024-USDCHF-M30-d07d7492 | liquidity_sweep / M30 | 0.1 | 0 | 0.00 | 0.00 | 0.00 | n/a | 0.000 | 0.00 |
| 92025-BTCUSDT-M15-9ed94308 | btc_mtf_trend_retest_reclaim / M15 | 0.25 | 0 | 0.00 | 0.00 | 0.00 | n/a | 0.000 | 0.00 |
| 92028-NZDUSD-M5-9217a733 | volume_sweep_reclaim / M5 | 0.05 | 15 | 0.24 | 1.69 | -1.45 | 0.571 | -0.215 | 1.86 |
| 92025-EURUSD-M5-96ae5733 | volume_sweep_reclaim / M5 | 0.05 | 1 | -0.54 | 1.06 | -1.60 | 0.000 | -0.378 | 1.60 |
| 92027-USDCHF-M5-b8818253 | volume_sweep_reclaim / M5 | 0.05 | 13 | -0.84 | 2.47 | -3.31 | 0.282 | -0.279 | 3.43 |
| 92026-GBPUSD-M5-e93068b3 | volume_sweep_reclaim / M5 | 0.05 | 12 | -3.18 | 1.31 | -4.49 | 0.220 | -0.438 | 5.45 |
| 92028-NZDUSD-M5-ca3505fc | volume_sweep_reclaim / M5 | 0.05 | 8 | -3.69 | 9.02 | -12.72 | 0.333 | -0.313 | 14.42 |
| 92023-NZDUSD-M30-57a5140f | liquidity_sweep / M30 | 0.1 | 126 | 71.19 | 84.38 | -13.19 | 0.977 | -0.012 | 135.13 |
| 92023-NZDUSD-M30-e1f842ad | liquidity_sweep / M30 | 0.1 | 126 | 71.19 | 84.38 | -13.19 | 0.977 | -0.012 | 135.13 |
| 92021-GBPUSD-M1-d16988c0 | trend_micro_burst_v2 / M1 | 0.35 | 382 | -6.22 | 61.74 | -67.96 | 0.129 | -0.470 | 67.96 |
| 92015-EURUSD-M5-6d73bb7e | liquidity_sweep / M5 | 0.9 | 718 | 11.21 | 82.90 | -71.69 | 0.853 | -0.109 | 82.03 |
| 92014-EURUSD-M1-9bee68d7 | trend_micro_burst_v2 / M1 | 0.35 | 790 | -4.27 | 108.77 | -113.05 | 0.199 | -0.378 | 113.05 |
| 92001-EURUSD-M5-7a22ac2e | liquidity_sweep / M5 | 0.5 | 444 | 423.72 | 542.93 | -119.22 | 0.947 | -0.029 | 373.18 |
| 92001-EURUSD-M5-f25a4498 | liquidity_sweep / M5 | 0.25 | 312 | 188.16 | 385.20 | -197.04 | 0.885 | -0.069 | 365.88 |
| 92015-EURUSD-M5-c55494ff | liquidity_sweep / M5 | 0.03 | 731 | 39.28 | 252.81 | -213.53 | 0.856 | -0.106 | 244.55 |
| 92021-GBPUSD-M1-17cc524d | trend_micro_burst_v2 / M1 | 0.02 | 382 | -31.09 | 308.70 | -339.78 | 0.129 | -0.470 | 339.78 |
| 92021-GBPUSD-M1-29289e65 | trend_micro_burst_v2 / M1 | 0.02 | 382 | -31.09 | 308.70 | -339.78 | 0.129 | -0.470 | 339.78 |
| 92001-EURUSD-M5-7d8e3532 | liquidity_sweep / M5 | 0.5 | 313 | 447.87 | 965.66 | -517.79 | 0.879 | -0.072 | 939.88 |
| 92014-EURUSD-M1-3317f626 | trend_micro_burst_v2 / M1 | 0.02 | 790 | -21.36 | 543.87 | -565.23 | 0.199 | -0.378 | 565.23 |

## Training-only selection on available instruments

The full 30-profile cohort cannot form a complete selection because BTCUSD is unsupported. This separate 29-profile cohort excludes BTCUSD explicitly. Each fold selects the highest positive net training return with at least 20 training trades; otherwise it holds cash.

Selected out-of-sample track: **-50.42 EUR net**, 134 trades, PF 0.923, average R -0.041, realized drawdown 168.28 EUR.

| Fold | Test start UTC | Test end UTC (exclusive) | Training-selected profile | Test net EUR |
|---:|---|---|---|---:|
| 1 | 2025-11-16 | 2025-12-16 | CASH | 0.00 |
| 2 | 2025-12-16 | 2026-01-15 | CASH | 0.00 |
| 3 | 2026-01-15 | 2026-02-14 | CASH | 0.00 |
| 4 | 2026-02-14 | 2026-03-16 | 92024-USDCHF-M30-3c27c3d9 | -17.95 |
| 5 | 2026-03-16 | 2026-04-15 | 92023-NZDUSD-M30-57a5140f | 8.64 |
| 6 | 2026-04-15 | 2026-05-15 | 92024-USDCHF-M30-3c27c3d9 | -31.81 |
| 7 | 2026-05-15 | 2026-06-14 | 92001-EURUSD-M5-7a22ac2e | -71.23 |
| 8 | 2026-06-14 | 2026-07-14 | 92024-USDCHF-M30-3c27c3d9 | 32.12 |
| 9 | 2026-07-14 | 2026-08-13 | 92024-USDCHF-M30-3c27c3d9 | 40.06 |
| 10 | 2026-08-13 | 2026-09-12 | 92024-USDCHF-M30-3c27c3d9 | -32.87 |
| 11 | 2026-09-12 | 2026-10-12 | 92023-NZDUSD-M30-57a5140f | -17.32 |
| 12 | 2026-10-12 | 2026-11-11 | 92008-EURUSD-M30-024e6fa9 | 39.93 |

## Files and limitations

- [Full structured report](report.json): individual windows, cost decomposition, branch settings, data hashes, and acquisition manifest.
- [Standalone HTML report](report.html): download/open locally for the full comparison.
- Raw snapshots and evaluation cache remain local under `history/mt5_20261111/` and are excluded from Git.
- Source code and regression tests are on this branch; the full suite passed with 167 tests and one expected failure.

OHLC simulation cannot reconstruct intrabar tick ordering, latency, partial fills, swap/financing, historical currency-conversion changes, or archived news blackouts. Drawdown is based on realized cash flows, including entry fees, not intratrade equity. Prior manual tuning may have used these dates; withheld evaluation windows do not establish that the dates were historically untouched.
