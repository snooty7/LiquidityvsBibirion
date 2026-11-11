# USDCHF M30 / M1: three strategy ideas

**Highest descriptive full-test net: `spread_0_9`, EUR 148.81 (1.488%).**

**Promotion:** no training-nominated upgrade passed all gates.

This ranking reports all six predeclared hypotheses, including rejected training candidates. It cannot override the frozen training nominations. These dates and side results were already examined; this is exploratory historical research, not untouched future validation.

## Which idea earns most?

| Family | Best full-test model (descriptive) | Net EUR | Later-six net EUR | Stressed later-six net EUR |
|---|---|---:|---:|---:|
| direction | sell_only | 98.76 | -19.40 | -33.13 |
| spread | spread_0_9 | 148.81 | 87.37 | 59.92 |
| exit | trail_gap_0_75 | 52.71 | 52.03 | 38.37 |

## All predeclared models: twelve test windows

| Model | Trades | Gross EUR | Spread EUR | Commission EUR | Slippage EUR | Net EUR | Return | PF | Realized DD EUR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| spread_0_9 | 141 | 278.52 | 65.81 | 39.48 | 24.42 | 148.81 | 1.488% | 1.236 | 69.87 |
| baseline | 143 | 279.56 | 66.89 | 40.04 | 24.77 | 147.86 | 1.479% | 1.231 | 69.87 |
| spread_1_2 | 143 | 279.56 | 66.89 | 40.04 | 24.77 | 147.86 | 1.479% | 1.231 | 69.87 |
| sell_only | 66 | 169.81 | 41.13 | 18.48 | 11.43 | 98.76 | 0.988% | 1.328 | 60.91 |
| trail_gap_0_75 | 152 | 187.10 | 65.51 | 42.56 | 26.32 | 52.71 | 0.527% | 1.077 | 95.10 |
| trail_gap_0_5 | 158 | 163.61 | 68.32 | 44.24 | 27.36 | 23.69 | 0.237% | 1.034 | 115.29 |
| buy_only | 86 | 46.15 | 28.53 | 24.08 | 14.89 | -21.35 | -0.214% | 0.947 | 107.12 |

## Later six windows and cost stress

| Model | Trades | Base net EUR | Base realized DD EUR | Stress net EUR | Stress realized DD EUR |
|---|---:|---:|---:|---:|---:|
| spread_0_9 | 62 | 87.37 | 42.12 | 59.92 | 48.04 |
| baseline | 62 | 93.87 | 42.12 | 66.33 | 48.04 |
| spread_1_2 | 62 | 93.87 | 42.12 | 66.33 | 48.04 |
| sell_only | 28 | -19.40 | 40.28 | -33.13 | 46.72 |
| trail_gap_0_75 | 66 | 52.03 | 55.01 | 38.37 | 63.18 |
| trail_gap_0_5 | 69 | 67.27 | 52.72 | 34.40 | 61.32 |
| buy_only | 41 | 51.65 | 61.91 | 44.23 | 53.85 |

## Frozen training nominations and promotion

Fixed nominations use only the first six preceding training windows. They cannot use later training/test winners. Aggregate fixed results include development overlap and are descriptive; the later six windows are the within-study confirmation subset. All dates were previously observed.

| Selection group | Fixed training choice | Full-test net EUR | Later-six net EUR | Stressed later-six net EUR | Promoted? |
|---|---|---:|---:|---:|---|
| direction | baseline | 147.86 | 93.87 | 66.33 | NO |
| spread | baseline | 147.86 | 93.87 | 66.33 | NO |
| exit | baseline | 147.86 | 93.87 | 66.33 | NO |
| overall | baseline | 147.86 | 93.87 | 66.33 | NO |

| Gate | direction | spread | exit | overall |
|---|---|---|---|---|
| alternative_selected_from_training | FAIL | FAIL | FAIL | FAIL |
| aggregate_net_improved | FAIL | FAIL | FAIL | FAIL |
| aggregate_drawdown_controlled | PASS | PASS | PASS | PASS |
| holdout_net_positive_and_improved | FAIL | FAIL | FAIL | FAIL |
| holdout_minimum_20_trades | PASS | PASS | PASS | PASS |
| holdout_drawdown_controlled | PASS | PASS | PASS | PASS |
| stress_net_positive_and_not_worse | PASS | PASS | PASS | PASS |

### Fixed nomination evidence

Overlapping training-window sums are selection diagnostics, not independent account returns.

| Candidate | Sum training net EUR | Sum realized DD EUR | Windows with >=20 trades | Rejection reasons |
|---|---:|---:|---:|---|
| buy_only | -1165.35 | 1465.44 | 6/6 | development-training net sum not positive and improved |
| sell_only | -505.46 | 1200.97 | 6/6 | development-training net sum not positive and improved |
| spread_1_2 | -1186.71 | 1650.88 | 6/6 | development-training net sum not positive and improved |
| spread_0_9 | -125.45 | 574.93 | 5/6 | development-training net sum not positive and improved |
| trail_gap_0_75 | -982.48 | 1697.75 | 6/6 | development-training net sum not positive and improved |
| trail_gap_0_5 | -1088.71 | 1551.24 | 6/6 | development-training net sum not positive and improved |

## Adaptive policies (each fold chooses from its own prior training)

| Group | Full-test net EUR | Later-six net EUR | Stressed later-six net EUR |
|---|---:|---:|---:|
| direction | 86.68 | 32.68 | 16.78 |
| spread | 141.37 | 87.37 | 59.92 |
| exit | 147.86 | 93.87 | 66.33 |
| overall | 123.00 | 69.00 | 45.53 |

Adaptive performance is reported separately; it does not approve a fixed profile or bypass promotion gates.

| Fold | Test start UTC | Direction choice | Spread choice | Exit choice | Overall choice |
|---:|---|---|---|---|---|
| 1 | 2025-11-16 | baseline | baseline | baseline | baseline |
| 2 | 2025-12-16 | baseline | baseline | baseline | baseline |
| 3 | 2026-01-15 | baseline | baseline | baseline | baseline |
| 4 | 2026-02-14 | baseline | spread_0_9 | baseline | spread_0_9 |
| 5 | 2026-03-16 | baseline | baseline | baseline | baseline |
| 6 | 2026-04-15 | baseline | spread_0_9 | baseline | spread_0_9 |
| 7 | 2026-05-15 | baseline | spread_0_9 | baseline | spread_0_9 |
| 8 | 2026-06-14 | sell_only | spread_0_9 | baseline | spread_0_9 |
| 9 | 2026-07-14 | baseline | spread_0_9 | baseline | spread_0_9 |
| 10 | 2026-08-13 | sell_only | spread_0_9 | baseline | spread_0_9 |
| 11 | 2026-09-12 | sell_only | spread_0_9 | baseline | sell_only |
| 12 | 2026-10-12 | baseline | baseline | baseline | baseline |

## Protocol

- USDCHF M30 setups / M1 confirmation with 300-bar context; native broker candles from the saved snapshot.
- Twelve 30-day tests, 16 November 2025 through 10 November 2026 UTC; 365 preceding training days and one-day embargo per fold.
- Base: observed historical spread, EUR 3.50/lot/side commission, 0.2-pip adverse market/stop slippage. Stress: EUR 7.00 and 0.4 pip; observed spreads unchanged and missing-spread fallback doubled from 1 to 2 pips.
- 0.1% risk, 20-pip initial SL, max lot 0.05, sizing/valuation fail-closed, one position per symbol, daily loss/exposure guards; no wider stops. Exit hypotheses only tighten the trailing gap; activation remains 1R.
- Replay defaults to the configured trade_side_filter, matching live; previously the replay default silently allowed both sides. Explicit --side remains an intentional research override. Live/replay share a finite, nonnegative spread gate with 1e-9-pip arithmetic tolerance at the boundary. All models including baseline are rerun.
- Seven fixed models only (baseline plus two per idea). No combinations or post-result parameter changes.
- Training nominations and gates were pushed before test replay. A prereplay JSON-container normalization amendment is recorded alongside the initial registration.
- These USDCHF dates and baseline/side results were previously examined; this is exploratory research, not untouched future validation.
- A test-period winner can reflect chance and multiple comparisons. No live readiness is inferred.
- Folds reset flat at EUR 10,000; returns sum without compounding. Drawdown measures realized cash flow, not intratrade equity.
- Native bid OHLC and historical spreads; assumed commission/slippage, constant symbol valuation; no swaps, latency or full tick reconstruction.
- Direction-only variants replay the entire signal/capacity path; they are not post-hoc deletion of losing trades.
- Saved-history research blocks MT5 initialization/order methods. No bot started, no orders sent, no active profile changed.

## Reproduction and audit

```powershell
.\.venv\Scripts\python.exe -m src.tools.research_usdchf_three_ideas --history history/mt5_20261111/USDCHF_extended.json --output reports/usdchf_three_ideas --workers 6
.\.venv\Scripts\python.exe -m src.tools.render_usdchf_three_ideas reports/usdchf_three_ideas/report.json
```

`plan.json` preserves the protocol, costs and code/data hashes; `locked_selections.json` records training choices. `report.json` includes every train/test/stress metric row. `test_trades.json` exposes exact test trade outcomes and cost components. `audit.json` records the independent reconstruction of all test rows and summaries, boundary/cost checks and stop/lot caps.
