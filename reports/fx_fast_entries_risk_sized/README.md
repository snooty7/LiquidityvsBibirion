# New M1/M5 scalp entries: EUR10,000, risk ceiling 0.75%

## Sizing-only supplementary study

Supplementary sizing-fidelity study after the retained0.5-lot outcomes were observed. All entry/exit definitions, thresholds, dates, costs and0.75% risk remain identical. Only the paper lot ceiling is the recorded broker maximum, so the shared sizer can actually use the requested risk budget. Earlier-only nominations are repeated and locked before later/full supplementary results; both studies retained. No live setting changed.

The [initial 0.5-lot-ceiling study](../fx_fast_entries/README.md) is retained with its original source commit and all outcomes. Only the paper volume ceiling changed here. This is not increased percentage risk or a new signal chosen after the later period. Risk is0.75% of current simulated equity, so the euro budget can change as equity compounds.


This is new entry research, not merely a shortened M30 exit. Three pure closed-bar entry definitions were fixed before outcomes and tested on all four available FX exports. No bot, orders, live configuration or production entry mode was enabled.

**Best full-period stressed result: EURUSD_m1_sweep_reclaim_stress, EUR106.13.** Earlier selection and later validation below must be considered separately. A positive full-period result containing selection data is not proof of a stable future edge.

All12 prototypes have later stressed net below zero: **True**. A candidate may improve total historical profit while failing this later check. No later-result winner replaces the frozen earlier nomination.

Common period: **2025-09-01 to 2026-11-11 exclusive**, approximately14 months. Every account starts independently at EUR10,000; no monthly resets, aggregation into a concurrent portfolio or guarantee of live returns.

## Earlier-selected candidates

Only participating, zero-financing/non-overnight candidates with positive earlier stressed net are eligible; otherwise cash. Tie lower sampled drawdown, then name. Selection was locked before later/full outcomes.

| Pair | Earlier nomination | Earlier stressed net | Later stressed net | Full normal net | Full stressed net | Full stressed drawdown |
|---|---|---:|---:|---:|---:|---:|
| EURUSD | M1 sweep/reclaim | EUR295.82 | EUR-182.89 | EUR293.42 | EUR106.13 | EUR363.21 |
| GBPUSD | cash; no eligible earlier candidate | - | - | - | - | - |
| NZDUSD | cash; no eligible earlier candidate | - | - | - | - | - |
| USDCHF | M5 sweep + M1 confirm | EUR77.75 | EUR-242.14 | EUR-2.46 | EUR-166.85 | EUR419.25 |

Earlier: 2025-09-01 to2026-03-01 exclusive. Later: 2026-03-02 to2026-11-11 exclusive, with one calendar day between. Separate earlier/later accounts each start flat and cannot be summed to reconstruct the continuous full account.

## Every prototype, including rejected candidates

| Pair | Entry | Full normal / stressed net | Stressed drawdown | Trades normal/stressed | EUR100-200 net winners normal/stressed | Mean initial price risk normal/stressed |
|---|---|---:|---:|---:|---:|---:|
| EURUSD | M1 sweep/reclaim | EUR293.42 / EUR106.13 | EUR363.21 | 23 / 23 | 3 / 1 | EUR76.21 / EUR75.55 |
| EURUSD | M1 EMA reclaim | EUR-82.78 / EUR-461.84 | EUR506.66 | 37 / 37 | 4 / 4 | EUR74.55 / EUR73.18 |
| EURUSD | M5 sweep + M1 confirm | EUR-500.51 / EUR-857.68 | EUR963.24 | 36 / 36 | 1 / 0 | EUR72.81 / EUR71.45 |
| GBPUSD | M1 sweep/reclaim | EUR-1,265.57 / EUR-2,030.30 | EUR2,176.44 | 88 / 88 | 12 / 11 | EUR70.65 / EUR67.58 |
| GBPUSD | M1 EMA reclaim | EUR-750.66 / EUR-1,711.54 | EUR1,835.79 | 100 / 100 | 13 / 11 | EUR71.72 / EUR67.95 |
| GBPUSD | M5 sweep + M1 confirm | EUR-977.93 / EUR-1,380.59 | EUR1,902.21 | 47 / 47 | 1 / 0 | EUR70.56 / EUR69.12 |
| NZDUSD | M1 sweep/reclaim | EUR-349.27 / EUR-471.98 | EUR502.07 | 13 / 13 | 0 / 0 | EUR73.74 / EUR73.23 |
| NZDUSD | M1 EMA reclaim | EUR-241.41 / EUR-411.52 | EUR440.25 | 16 / 16 | 1 / 1 | EUR73.54 / EUR72.94 |
| NZDUSD | M5 sweep + M1 confirm | EUR-355.79 / EUR-513.96 | EUR696.05 | 16 / 16 | 1 / 1 | EUR73.10 / EUR72.54 |
| USDCHF | M1 sweep/reclaim | EUR-673.41 / EUR-852.55 | EUR852.55 | 25 / 25 | 2 / 2 | EUR71.39 / EUR70.68 |
| USDCHF | M1 EMA reclaim | EUR-515.42 / EUR-659.78 | EUR865.78 | 26 / 26 | 2 / 3 | EUR71.36 / EUR70.95 |
| USDCHF | M5 sweep + M1 confirm | EUR-2.46 / EUR-166.85 | EUR419.25 | 17 / 17 | 1 / 1 | EUR75.10 / EUR74.38 |

All trades, losses and target-band counts use net results after modeled costs. Drawdown includes M1-close open P&L, incurred entry fees and actual simulated exit fills; intrabar/tick drawdown can be greater.

## Entry definitions and unchanged controls

All models use M1 decisions, completed M5 EMA20/EMA50 trend and EMA20 slope over3 prior M5 bars. Confirming M1 body is at least60% of range and range at least1.2 times the preceding20-range mean. Sweep penetration exceeds0.2 pip. Spread cap is0.7 pip.

- M1 sweep/reclaim: prior M1 sweeps12 earlier M1 extrema and closes back inside; the current directional candle confirms beyond that sweep candle's opposite edge.
- M1 EMA reclaim: prior M1 sweeps4 earlier extrema and closes against the M5 trend across M1 EMA20; current M1 reclaims EMA20 and the prior candle's opposite edge.
- M5 sweep/M1 confirm: latest completed M5 sweeps12 prior M5 extrema and reclaims them; M1 then confirms beyond its preceding2 extrema while that setup remains the latest closed M5, within1-5 minutes. One entry confirmation per sweep.

Initial SL is behind the swept/last5 M1 extreme with0.2-pip padding. Raw bid-close structure distance must be6-15 pips; rejected stops are not widened to meet a preferred distance. Lots are sized on the actual adverse filled entry-to-stop distance, including spread/slippage. Initial target remains2R, trailing activates1.5R with1R gap and removes TP at activation. Existing stops never move farther away.

Initial price-risk budget<=0.75%; paper volume ceiling is each symbol's recorded broker maximum, not a fixed lot size. Shared risk sizer rounds down from the requested risk budget and actual stop distance.0.75% aggregate exposure,EUR150 daily trigger,single-position rule and original3600-second cooldown retained. No widened existing stops, averaging or martingale. Margin constraints not reconstructed.

The risk percentage is a maximum, not a promise that every position uses the full budget. The actual average initial risk in the table makes volume-ceiling effects explicit. Fees/gaps can add to a price-stop loss. Historical margin requirements and changing EUR conversions are not reconstructed.

Both directions retain the30-minute cap, daytime UTC entries05:00-18:00 intersected with existing sessions, and flat-by19:00 policy. Original3600-second cooldown is retained. Swap stays actively modeled and every position is audited against both rollover clocks; all48 accounts have zero swap, zero overnight positions and zero late exits.

## Costs, evidence and limitations

Normal: observed M1 historical spreads,1-pip fallback, EUR3.50 commission/lot/side and0.2-pip adverse market/stop slippage. Stress doubles commission/slippage and negative swap debits while preserving positive credits; fallback spread becomes2 pips. Observed spreads are not doubled. TP-limit exits have no exit slippage. These remain declared cost assumptions, not a broker invoice.

The same four histories, per-pair constant EUR tick valuations and financing snapshot as the previous scalp study are used. NZDUSD limits the common comparison to September2025 onward. Current swap rates are held constant with the prior explicit Wednesday triple-day assumption, but financing is zero in all observed paths under both GMT+3 and GMT+2 audit schedules.

There is no parameter grid, pair-specific tuning or post-result change to entry thresholds. These prices and dates were examined repeatedly in prior research; the later period is not an untouched holdout. Candidate counts are small and disclosed. Full ranking is descriptive; earlier profit alone cannot establish reliability. Source OHLC cannot reconstruct tick-level spread/latency/liquidity or all historical broker stop/margin constraints.

Pure signal definitions contain no broker calls and can be reused by a future live adapter, but current dispatch is offline only and requires explicit history. The research configuration is not an enabled production strategy. Existing entry/exit risk and cost code is shared.

## Validation and reproduction

**393 passed, one existing expected failure.** New tests cover each setup on BUY/SELL, future-bar invariance, M5-close ordering, insufficient displacement/structural width, immutable structural protection, offline-only guards, decision-clock validation, earlier-only/cash nomination and cached-vs-full replay equality for final/time/daily/stop exits in both directions.

Only entry feature construction is skipped on no-signal minutes. Every open-position M1 bar is still processed for SL/TP, financing, daily protection and elapsed exits; the regression comparison verifies identical trades and balances with this optimization disabled. Independent report audit reconciles all48 trade/cost ledgers, target-band counts, lot ceilings and per-entry0.75% price-risk bounds.

The frozen plan records all hypotheses, reference/history/source digests, precise settings and selection rules. Keep the original source commit and use a new output directory after changing source or assumptions. No bot was started and no order was placed.

Reproduction for this source version:

```powershell
python -m src.tools.research_fast_scalp_entries --history-root history/mt5_20261111 --output reports/fx_fast_entries_risk_sized --risk-sized-volume --workers 6
```

Actual simulated volumes in the supplementary study ranged from 0.49 to 1.35 lots. The recorded broker ceiling is a maximum, not an order size; every position remained within0.75% of its entry-time simulated equity before execution costs.
