# USDCHF M30 / M1 long-entry filter

**Decision: does not pass promotion; no upgrade approved.**

Profit after execution costs is the primary ranking objective. Risk sizing, initial stops, daily/exposure protection and trailing rules are unchanged. Active profiles keep the new filter off.

Neither threshold qualified in any training window. The filtered policy therefore stayed off in every test window. Its test profits below are baseline profits, not evidence that the filter improved performance. Standalone rejected thresholds were not replayed on the test windows.

## Cost-aware test results

| Scope | Model | Trades | Net EUR | Return on EUR 10,000 | PF | Realized DD EUR |
|---|---|---:|---:|---:|---:|---:|
| aggregate | baseline | 143 | 147.86 | 1.479% | 1.231 | 69.87 |
| aggregate | filtered_policy | 143 | 147.86 | 1.479% | 1.231 | 69.87 |
| confirmation | baseline | 62 | 93.87 | 0.939% | 1.376 | 42.12 |
| confirmation | filtered_policy | 62 | 93.87 | 0.939% | 1.376 | 42.12 |
| stress_confirmation | baseline | 62 | 66.33 | 0.663% | 1.252 | 48.04 |
| stress_confirmation | filtered_policy | 62 | 66.33 | 0.663% | 1.252 | 48.04 |

Returns sum independent monthly folds, each starting flat with EUR 10,000; no compounding. Drawdown is realized cash-flow drawdown, not intratrade equity drawdown.

| Scope | Model | BUY trades | BUY net EUR | SELL trades | SELL net EUR |
|---|---|---:|---:|---:|---:|
| aggregate | baseline | 86 | 0.86 | 57 | 147.00 |
| aggregate | filtered_policy | 86 | 0.86 | 57 | 147.00 |
| confirmation | baseline | 38 | 79.11 | 24 | 14.75 |
| confirmation | filtered_policy | 38 | 79.11 | 24 | 14.75 |
| stress_confirmation | baseline | 38 | 63.49 | 24 | 2.84 |
| stress_confirmation | filtered_policy | 38 | 63.49 | 24 | 2.84 |

SELL rules are unchanged; fewer long positions can change which later SELL opportunities fit within the existing one-position limit.

## Promotion gates

| Gate | Result |
|---|---|
| filter_selected | FAIL |
| aggregate_net_improved | FAIL |
| aggregate_drawdown_controlled | PASS |
| confirmation_positive_and_improved | FAIL |
| confirmation_sample_20 | PASS |
| confirmation_drawdown_controlled | PASS |
| stress_positive_and_not_worse | PASS |

## Training decisions

Each window fits two nonnegative thresholds (Q25/Q50) from baseline training BUY-entry features. The feature is H4 EMA20 rise over three closed bars divided by 14-bar mean true range, with a fixed 80-bar EMA context. Quantile fitting never uses profit labels. Full filtered training replays then choose the highest total net profit subject to positive BUY net, positive/improved total net, at least 20 retained BUY trades and drawdown <=1.25 baseline. If neither qualifies, the policy uses the unfiltered baseline.

| Fold | Q25 threshold | Q50 threshold | Selected |
|---:|---:|---:|---|
| 1 | 0.04659465638756012 | 0.16088485401273037 | off |
| 2 | 0.04908048865917583 | 0.16289538805320547 | off |
| 3 | 0.038416506934315135 | 0.1585120360155965 | off |
| 4 | 0.028301653962456715 | 0.14327823091278163 | off |
| 5 | 0.005498278717409125 | 0.1419938242180935 | off |
| 6 | 0.0 | 0.13432595388168905 | off |
| 7 | 0.011261894761672539 | 0.1419938242180935 | off |
| 8 | 0.017025510805935954 | 0.15074664848988986 | off |
| 9 | 0.014143702783804248 | 0.14327823091278163 | off |
| 10 | 0.003510299801780712 | 0.1419938242180935 | off |
| 11 | 0.006866036251863238 | 0.13432595388168905 | off |
| 12 | 0.021602561066214936 | 0.1662191082544294 | off |

Overlapping training windows are selection diagnostics, not independent investment returns.

| Fold | Candidate | Training net EUR | BUY trades | BUY net EUR | Realized DD EUR | Rejection reasons |
|---:|---|---:|---:|---:|---:|---|
| 1 | off | -212.72 | 87 | -136.54 | 272.76 | baseline |
| 1 | q25 | -239.29 | 67 | -163.11 | 263.01 | training BUY net not positive; training total net not positive and improved |
| 1 | q50 | -108.89 | 48 | -32.71 | 162.27 | training BUY net not positive; training total net not positive and improved |
| 2 | off | -165.18 | 86 | -105.48 | 304.95 | baseline |
| 2 | q25 | -175.04 | 66 | -115.33 | 266.42 | training BUY net not positive; training total net not positive and improved |
| 2 | q50 | -34.21 | 45 | 25.50 | 157.45 | training total net not positive and improved |
| 3 | off | -264.29 | 82 | -207.44 | 304.95 | baseline |
| 3 | q25 | -242.88 | 62 | -186.04 | 271.90 | training BUY net not positive; training total net not positive and improved |
| 3 | q50 | -114.28 | 44 | -57.43 | 175.68 | training BUY net not positive; training total net not positive and improved |
| 4 | off | -138.41 | 76 | -158.87 | 283.05 | baseline |
| 4 | q25 | -142.61 | 59 | -163.08 | 268.22 | training BUY net not positive; training total net not positive and improved |
| 4 | q50 | -46.21 | 43 | -66.68 | 182.47 | training BUY net not positive; training total net not positive and improved |
| 5 | off | -161.70 | 81 | -146.72 | 280.51 | baseline |
| 5 | q25 | -135.14 | 63 | -120.16 | 256.01 | training BUY net not positive; training total net not positive and improved |
| 5 | q50 | -67.15 | 47 | -52.17 | 191.58 | training BUY net not positive; training total net not positive and improved |
| 6 | off | -129.50 | 90 | -150.76 | 280.51 | baseline |
| 6 | q25 | -127.68 | 69 | -148.95 | 256.01 | training BUY net not positive; training total net not positive and improved |
| 6 | q50 | -43.67 | 51 | -64.94 | 200.70 | training BUY net not positive; training total net not positive and improved |
| 7 | off | -147.42 | 91 | -171.56 | 280.51 | baseline |
| 7 | q25 | -171.28 | 72 | -195.42 | 249.84 | training BUY net not positive; training total net not positive and improved |
| 7 | q50 | -61.27 | 53 | -85.41 | 191.58 | training BUY net not positive; training total net not positive and improved |
| 8 | off | -87.94 | 93 | -158.83 | 280.51 | baseline |
| 8 | q25 | -99.76 | 74 | -170.65 | 238.44 | training BUY net not positive; training total net not positive and improved |
| 8 | q50 | -11.38 | 54 | -82.27 | 184.79 | training BUY net not positive; training total net not positive and improved |
| 9 | off | -91.90 | 92 | -145.73 | 280.51 | baseline |
| 9 | q25 | -119.05 | 75 | -172.88 | 238.44 | training BUY net not positive; training total net not positive and improved |
| 9 | q50 | -15.73 | 55 | -69.56 | 182.47 | training BUY net not positive; training total net not positive and improved |
| 10 | off | -40.97 | 91 | -159.09 | 231.44 | baseline |
| 10 | q25 | -56.19 | 73 | -174.31 | 198.48 | training BUY net not positive; training total net not positive and improved |
| 10 | q50 | 14.83 | 55 | -103.29 | 151.63 | training BUY net not positive |
| 11 | off | 27.45 | 94 | -133.87 | 129.99 | baseline |
| 11 | q25 | 1.04 | 77 | -160.28 | 94.76 | training BUY net not positive; training total net not positive and improved |
| 11 | q50 | 96.22 | 55 | -65.10 | 66.12 | training BUY net not positive |
| 12 | off | 127.94 | 92 | -50.31 | 74.79 | baseline |
| 12 | q25 | 101.52 | 75 | -76.72 | 67.48 | training BUY net not positive; training total net not positive and improved |
| 12 | q50 | 155.81 | 54 | -22.44 | 65.28 | training BUY net not positive |

## Monthly test windows

| Fold | Start UTC | Selection | Baseline net EUR | Policy net EUR |
|---:|---|---|---:|---:|
| 1 | 2025-11-16 | off | -9.42 | -9.42 |
| 2 | 2025-12-16 | off | 2.36 | 2.36 |
| 3 | 2026-01-15 | off | 60.02 | 60.02 |
| 4 | 2026-02-14 | off | -17.95 | -17.95 |
| 5 | 2026-03-16 | off | 50.79 | 50.79 |
| 6 | 2026-04-15 | off | -31.81 | -31.81 |
| 7 | 2026-05-15 | off | 16.96 | 16.96 |
| 8 | 2026-06-14 | off | 32.12 | 32.12 |
| 9 | 2026-07-14 | off | 40.06 | 40.06 |
| 10 | 2026-08-13 | off | -32.87 | -32.87 |
| 11 | 2026-09-12 | off | 17.47 | 17.47 |
| 12 | 2026-10-12 | off | 20.12 | 20.12 |

## Protocol and limitations

- Twelve nonoverlapping 30-day tests from 16 November 2025 through 10 November 2026 UTC. Each has 365 preceding training days and a one-day embargo; later six windows are the confirmation subset.
- Thresholds and choices were locked before test replay. No threshold tuning or gate relaxation after test results.
- Historical bid candles and observed spreads, assumed EUR 3.50/lot/side commission, 0.2-pip adverse market/stop slippage. Stress doubles commission/slippage to EUR 7.00 and 0.4 pip; observed spreads stay unchanged, with missing-spread fallback increasing from 1 to 2 pips.
- Entry-bias EMA now uses the same configured count of closed bars in live and replay (previously live included a forming bar in its count while replay used an arbitrary 120-bar minimum). Both models are rerun with this alignment.
- This freshly aligned M1 baseline supersedes earlier descriptive M1 numbers for comparison with this filter.
- These historical dates were previously examined; this is not untouched future validation.
- Training windows overlap; their sums are not independent observations or portfolio returns.
- SELL rules are unchanged, but realized SELL opportunities can differ when fewer long positions occupy capacity.
- Commission/slippage are unverified assumptions; no swap, latency or full tick reconstruction.
- Historical symbol valuation is held constant. Small gains are sensitive to unmodeled costs and execution effects.
- Existing risk limits stay in place: 0.1% risk, 20-pip initial stop, 0.05 max lot, one position; no sizing increase.
- Saved history only. Broker initialization and trading calls are blocked during research. No bot was started.

Reproduce from the saved history:

```powershell
.\.venv\Scripts\python.exe -m src.tools.research_long_filter --history history/mt5_20261111/USDCHF_extended.json --output reports/usdchf_long_filter --workers 6
.\.venv\Scripts\python.exe -m src.tools.render_long_filter_report reports/usdchf_long_filter/report.json
```

The plan, locked selections, per-fold results, costs and source/data hashes are recorded in the adjacent JSON files.
