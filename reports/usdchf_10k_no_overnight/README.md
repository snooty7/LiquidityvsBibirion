# USDCHF M30/M1: pre-rollover exits, EUR10,000, risk 0.75%

**Result: closing only SELL positions before rollover improves stressed profitability. Closing both sides does not.** The SELL-only variant returns EUR788.31 (+7.88%) under normal modeled costs and EUR131.37 (+1.31%) under stressed costs in the primary clock scenario. These are total returns over nearly two years, not annual or monthly returns.

All 36 independent continuous-account replays completed: three fixed variants, two rollover clocks, two cost levels, and three windows. Capital EUR10,000; entry risk 0.75% (EUR75 initial price-risk budget), trailing activation 1.5R, gap 1R, initial target 2R removed on activation. No parameter search, no risk increase and no live deployment.

Full account period: **2024-11-15 00:00 UTC to 2026-11-11 00:00 UTC exclusive**. Each replay starts once, without monthly resets.

## Primary result: fixed broker clock GMT+3

| Variant | Costs including swap | Net profit | Total return | Largest sampled equity drawdown | Net winners EUR100–200 / all trades | Win rate |
|---|---|---:|---:|---:|---:|---:|
| Existing candidate | Normal | EUR796.12 | 7.96% | EUR774.93 | 23 / 148 | 43.24% |
| Existing candidate | Stressed | EUR-465.41 | -4.65% | EUR961.06 | 17 / 146 | 41.78% |
| SELL flat before rollover | Normal | EUR788.31 | 7.88% | EUR731.81 | 26 / 158 | 42.41% |
| SELL flat before rollover | Stressed | EUR131.37 | 1.31% | EUR741.88 | 23 / 156 | 42.31% |
| BUY and SELL flat before rollover | Normal | EUR12.64 | 0.13% | EUR720.83 | 15 / 186 | 48.92% |
| BUY and SELL flat before rollover | Stressed | EUR-669.16 | -6.69% | EUR827.62 | 13 / 186 | 47.85% |

With stressed costs, SELL-only flattening improves net profit by EUR596.78 versus baseline and reduces sampled drawdown by EUR219.18. Its win rate is 42.31%, while both-side flattening has a higher 47.85% win rate but loses EUR669.16. Win rate alone does not measure account profitability.

Counts in the EUR100–200 band are inclusive and use individual trade net profit after all modeled costs. Total account P&L includes losses. Drawdown includes open P&L at observed M1 closes, entry fees, financing cash flows and simulated exit fills; intrabar/tick drawdown can be larger.

## Clock sensitivity and remaining overnight exposure

Both clocks were declared before outcomes; GMT+2 is a sensitivity, not a clock selected for its better result. The SELL-only variant is positive at stressed costs under both clocks; the both-side variant is negative under both clocks.

| Variant | Clock | Costs | Net profit | Largest sampled drawdown | Net winners EUR100–200 / all trades | Net swap | Affected-side trades with financing |
|---|---|---|---:|---:|---:|---:|---:|
| Existing candidate | GMT+3 | Normal | EUR796.12 | EUR774.93 | 23 / 148 | EUR-433.24 | 0 |
| Existing candidate | GMT+3 | Stressed | EUR-465.41 | EUR961.06 | 17 / 146 | EUR-906.42 | 0 |
| Existing candidate | GMT+2 | Normal | EUR855.92 | EUR777.49 | 23 / 148 | EUR-368.39 | 0 |
| Existing candidate | GMT+2 | Stressed | EUR-320.87 | EUR901.22 | 17 / 145 | EUR-783.66 | 0 |
| SELL flat before rollover | GMT+3 | Normal | EUR788.31 | EUR731.81 | 26 / 158 | EUR64.56 | 0 |
| SELL flat before rollover | GMT+3 | Stressed | EUR131.37 | EUR741.88 | 23 / 156 | EUR62.27 | 0 |
| SELL flat before rollover | GMT+2 | Normal | EUR1,017.71 | EUR727.68 | 25 / 158 | EUR63.78 | 0 |
| SELL flat before rollover | GMT+2 | Stressed | EUR351.82 | EUR740.23 | 21 / 156 | EUR61.45 | 0 |
| BUY and SELL flat before rollover | GMT+3 | Normal | EUR12.64 | EUR720.83 | 15 / 186 | EUR0.00 | 0 |
| BUY and SELL flat before rollover | GMT+3 | Stressed | EUR-669.16 | EUR827.62 | 13 / 186 | EUR0.00 | 0 |
| BUY and SELL flat before rollover | GMT+2 | Normal | EUR476.27 | EUR727.82 | 16 / 186 | EUR0.00 | 0 |
| BUY and SELL flat before rollover | GMT+2 | Stressed | EUR-181.02 | EUR770.14 | 15 / 186 | EUR0.00 | 0 |

Only SELL is affected by the SELL-only policy; BUY can still carry and earn or pay financing. Missing cutoff quotes are not replaced by invented fills. Remaining financing on an affected side, if any in the table, is charged at actual modeled rollover before the first available exit. Baseline has no affected side because no flattening policy is enabled.

## Earlier and later periods

Each window below starts independently at EUR10,000. Values cannot be added to reproduce the continuous full-period account.

| Variant | Clock | Earlier normal net | Earlier stressed net | Later normal net | Later stressed net |
|---|---|---:|---:|---:|---:|
| Existing candidate | GMT+3 | EUR-98.10 | EUR-266.04 | EUR886.35 | EUR-174.63 |
| Existing candidate | GMT+2 | EUR-88.90 | EUR-247.64 | EUR951.64 | EUR-62.21 |
| SELL flat before rollover | GMT+3 | EUR-126.03 | EUR-234.37 | EUR935.88 | EUR388.40 |
| SELL flat before rollover | GMT+2 | EUR-99.77 | EUR-210.95 | EUR1,144.40 | EUR577.76 |
| BUY and SELL flat before rollover | GMT+3 | EUR-425.95 | EUR-505.50 | EUR444.04 | EUR-148.13 |
| BUY and SELL flat before rollover | GMT+2 | EUR-374.44 | EUR-450.03 | EUR924.02 | EUR295.17 |

Earlier: 2024-11-15 to 2025-11-15 exclusive. Later: 2025-11-16 to 2026-11-11 exclusive. The SELL-only variant still loses EUR234.37 in the earlier stressed GMT+3 account. The rule improves the complete historical cost test but does not eliminate bad periods.

## Fixed execution policy

- Existing candidate: overnight positions allowed, as in the prior swap study.
- SELL-only variant: close SELL at the first M1 bar open at or after 23:55 broker time; BUY unchanged.
- Both-side variant: apply the same rule to BUY and SELL.
- Block new affected-side entries from 23:55 inclusive to midnight exclusive; no automatic reopening. Otherwise use the original signals, sessions and cooldown.
- Affected positions remain due for exit after a missing-quote/weekend gap; use the first available actual bid/ask and charge any financing already incurred. Never backdate the fill.
- Daily loss protection takes priority. Forced market exits incur observed spread, commission and adverse slippage. No stop is widened. No existing target was crossed at a forced cutoff open in the completed ledgers.

Risk controls are identical in all variants: 0.75% risk-derived entry sizing, 0.75% aggregate paper exposure cap, max lot 0.5, EUR150 daily trigger, one-position rule, 20-pip initial stop, spread cap 0.9 pips, original per-trade protection and trailing. The new exit policy is an optional offline replay argument; no live configuration or execution adapter was changed.

## Costs and limitations

All variants reuse exactly the [previous swap study](../usdchf_10k_swap/README.md) history and broker metadata, not newly selected prices or different cost assumptions. Normal costs: historical observed spread (1-pip fallback), EUR3.50 commission per lot per side and 0.2-pip adverse market/stop slippage. Stress: EUR7, 0.4 pip, negative swap debits doubled and positive credits unchanged. **Observed spreads are not doubled**; missing-spread fallback becomes 2 pips. Take-profit limit exits retain their existing no-exit-slippage convention.

The 2026-11-12 broker snapshot has point rates +1.41113636 BUY and -25.75364 SELL. With the existing constant EUR tick valuation, these become +EUR1.52740222 and -EUR27.87552496 per lot/day before weekday weights. These current rates are held constant over historical dates; actual historical swap rates and EUR conversions are unavailable. MT5 returned invalid triple-day code 7, so the same explicit Wednesday triple-day assumption is retained. Historical clock/DST policy is unknown; fixed GMT+3 and GMT+2 scenarios are both reported.

The dates and earlier candidate outcomes have been examined repeatedly. The cutoff was fixed at five minutes before midnight, with no tuning after results. This is exploratory historical comparison, not untouched walk-forward evidence or a promise of future returns. Historical margin requirements, changing broker stop constraints, latency, unavailable liquidity and tick extrema are not reconstructed. A higher broker leverage setting does not itself change these risk-derived simulated volumes; margin constraints were not modeled.

## Validation and reproduction

**343 tests passed; one existing expected failure.** Fourteen new cases cover side scope, exact cutoff and midnight reset, quote gaps, retained swap after late fills, cost accounting, entry blackout, daily-guard priority, avoidance of a later minute high/close in cutoff execution, invalid cutoffs and JSON-normalized baseline verification. All use synthetic history and prohibit broker calls.

All 12 baseline ledgers match the preceding swap study exactly after JSON normalization. Independent checks reconciled all 36 account balances, every trade cost/swap ledger and target-band count. Zero cutoff fills conflict with an existing take-profit at the opening quote.

Initial simulations completed, but an audit incorrectly compared in-memory swap-event tuples with JSON lists and stopped before saving. The initial registration is retained in `initial_registration.json`. The amendment changes only the source digest and disclosed validation explanation; all trading assumptions are identical. JSON-normalized audit and recoverable checkpoint writing were added, and all 36 simulations were repeated.

```powershell
python -m src.tools.research_no_overnight --history history/mt5_20261111/USDCHF_extended.json --reference reports/usdchf_10k_swap/report.json --output reports/usdchf_10k_no_overnight --workers 6
```

The plan and source/history hashes are frozen before replays. Use a new output directory after a source or protocol change. Each research process forbids broker initialization and trading operations. No bot was started and no order was placed.
