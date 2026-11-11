# USDCHF M30 improvement study

**Decision: does not pass promotion gates; retain baseline.** Training-nominated fixed candidate: `baseline`.

## Corrected baseline

The previous all-branch report supplied M1 candles to confirmation even when USDCHF M30 requested M5. That fidelity bug is fixed and regression-tested. Its earlier EUR +147.86 result is superseded for this configured branch. With faithful M5 confirmation, the baseline is **64 trades, EUR +18.06 net**, PF 1.060 and realized drawdown EUR 76.32.

## Protocol and limits

- Eight hypotheses were registered: baseline, later/wider trailing, fixed 2R/1.5R targets, fresher confirmation, stronger displacement.
- Risk remains 0.1%, initial stop 20 pips and maximum lot 0.05. No position-size increase, stop widening, averaging or grid logic was introduced.
- The original 90-day diagnostic failed minimum training sample requirements. It is retained in `../usdchf_m30_initial_90d/`.
- Additional older broker history starts 1 October 2024. Training extends backward to 365 days while the twelve original nonoverlapping 30-day test windows stay unchanged.
- Before any alternative OOS replay, six later test folds (15 May–10 November 2026 UTC) were reserved for confirmation because the known baseline had only 14 trades in three folds. The unchanged confirmation minimum is 20 trades. The amendment is recorded beside the initial diagnostic.
- The fixed candidate is chosen from the first six training windows only, maximizing net minus 0.5 realized drawdown, with sample and drawdown constraints. Later training windows cannot influence that fixed nomination.
- An independently declared adaptive track chooses again using only each fold's preceding training data. A baseline fallback is used when no alternative qualifies. The fixed-profile aggregate over all twelve windows is descriptive because its development portion overlaps nomination training; only the last six reserved windows are confirmatory for that fixed nomination.
- Observed spreads, EUR 3.50/lot/side assumed commission and 0.2-pip adverse market/stop slippage are included. Confirmation stress doubles commission/slippage to EUR 7.00 and 0.4 pip; observed spreads remain unchanged, and missing-spread fallback doubles from 1 to 2 pips.
- Folds start flat with EUR 10,000. Results sum independent fold returns, without compounding. Drawdown is realized cash-flow drawdown, not intratrade equity drawdown.
- These dates and baseline were examined previously. This is historical validation, not a genuinely untouched future sample. Overlapping training windows are not independent observations.
- Native broker candles and original EUR symbol valuation are retained. No broker connection occurs during replay; the historical extension used read-only MT5 access with AutoTrading disabled.

## Cost-aware results

| Scope | Track | Trades | Gross EUR | Costs EUR | Net EUR | PF | Avg R | Realized DD EUR |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| All 12 test windows (fixed is descriptive) | baseline | 64 | 67.02 | 48.96 | 18.06 | 1.060 | 0.032 | 76.32 |
| All 12 test windows (fixed is descriptive) | fixed | 64 | 67.02 | 48.96 | 18.06 | 1.060 | 0.032 | 76.32 |
| All 12 test windows (fixed is descriptive) | adaptive | 60 | 31.04 | 46.07 | -15.02 | 0.952 | -0.029 | 85.85 |
| Reserved 6 confirmation folds | baseline | 24 | 11.21 | 17.72 | -6.50 | 0.929 | -0.031 | 73.64 |
| Reserved 6 confirmation folds | fixed | 24 | 11.21 | 17.72 | -6.50 | 0.929 | -0.031 | 73.64 |
| Reserved 6 confirmation folds | adaptive | 20 | -24.77 | 14.82 | -39.59 | 0.608 | -0.226 | 85.85 |
| Confirmation under cost stress | baseline | 24 | 10.17 | 28.68 | -18.51 | 0.809 | -0.087 | 79.48 |
| Confirmation under cost stress | fixed | 24 | 10.17 | 28.68 | -18.51 | 0.809 | -0.087 | 79.48 |

## Promotion gates

| Gate | Result |
|---|---|
| alternative_selected_from_training | FAIL |
| aggregate_net_improved | FAIL |
| aggregate_drawdown_controlled | PASS |
| holdout_net_positive_and_improved | FAIL |
| holdout_minimum_20_trades | PASS |
| holdout_drawdown_controlled | PASS |
| stress_net_positive_and_not_worse | FAIL |

## Training evidence (development windows only)

Training windows overlap; these sums are selection diagnostics, not independent performance estimates.

| Candidate | Windows with at least 20 trades | Sum training net EUR | Sum penalized score |
|---|---:|---:|---:|
| baseline | 6 / 6 | -786.74 | -1,349.14 |
| trail_later_1_5 | 6 / 6 | -886.57 | -1,503.49 |
| trail_later_2 | 6 / 6 | -1,157.29 | -1,841.92 |
| trail_wider_1_5 | 6 / 6 | -620.95 | -1,138.09 |
| fixed_2r | 6 / 6 | -1,157.29 | -1,841.92 |
| fixed_1_5r | 6 / 6 | -583.52 | -1,011.92 |
| fresh_confirmation | 6 / 6 | -480.25 | -819.38 |
| stronger_displacement | 6 / 6 | -592.06 | -1,043.31 |

## Individual test folds

| Fold | Test start UTC | Baseline net | Fixed net | Adaptive choice | Adaptive net |
|---:|---|---:|---:|---|---:|
| 1 | 2025-11-16 | -42.55 | -42.55 | baseline | -42.55 |
| 2 | 2025-12-16 | -33.63 | -33.63 | baseline | -33.63 |
| 3 | 2026-01-15 | 38.89 | 38.89 | baseline | 38.89 |
| 4 | 2026-02-14 | 22.13 | 22.13 | baseline | 22.13 |
| 5 | 2026-03-16 | 40.39 | 40.39 | baseline | 40.39 |
| 6 | 2026-04-15 | -0.66 | -0.66 | baseline | -0.66 |
| 7 | 2026-05-15 | 4.98 | 4.98 | baseline | 4.98 |
| 8 | 2026-06-14 | -15.13 | -15.13 | trail_wider_1_5 | -27.34 |
| 9 | 2026-07-14 | -14.52 | -14.52 | baseline | -14.52 |
| 10 | 2026-08-13 | -25.63 | -25.63 | baseline | -25.63 |
| 11 | 2026-09-12 | 37.44 | 37.44 | stronger_displacement | 16.56 |
| 12 | 2026-10-12 | 6.35 | 6.35 | baseline | 6.35 |

## Reproduce

```powershell
python -m src.tools.research_usdchf_m30 --history history/mt5_20261111/USDCHF_extended.json --train-days 365 --development-folds 6 --workers 6 --output reports/usdchf_m30_improvement
```

`plan.json` freezes hypotheses and gates; `locked_selections.json` records selections before alternative test replay; `report.json` contains the complete metrics, per-fold results and promotion decision. Raw broker data and replay cache stay local and are excluded from Git.

OHLC ordering, latency, partial fills, swap/financing, historical currency conversion and archived news blackouts are not fully simulated. Costs remain unverified assumptions. This study makes no profitability guarantee.
