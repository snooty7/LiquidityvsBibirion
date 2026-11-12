**Supplement:** a [risk-budget sizing check](../fx_fast_entries_risk_sized/README.md) repeats the unchanged entries using recorded broker volume ceilings, retaining the0.75% budget. The original0.5-lot results below are preserved.

# New M1/M5 scalp entries: EUR10,000, risk ceiling 0.75%

This is new entry research, not merely a shortened M30 exit. Three pure closed-bar entry definitions were fixed before outcomes and tested on all four available FX exports. No bot, orders, live configuration or production entry mode was enabled.

**Best full-period stressed result: EURUSD_m1_sweep_reclaim_stress, EUR44.08.** Earlier selection and later validation below must be considered separately. A positive full-period result containing selection data is not proof of a stable future edge.

All12 prototypes have later stressed net below zero: **True**. A candidate may improve total historical profit while failing this later check. No later-result winner replaces the frozen earlier nomination.

Common period: **2025-09-01 to 2026-11-11 exclusive**, approximately14 months. Every account starts independently at EUR10,000; no monthly resets, aggregation into a concurrent portfolio or guarantee of live returns.

## Earlier-selected candidates

Only participating, zero-financing/non-overnight candidates with positive earlier stressed net are eligible; otherwise cash. Tie lower sampled drawdown, then name. Selection was locked before later/full outcomes.

| Pair | Earlier nomination | Earlier stressed net | Later stressed net | Full normal net | Full stressed net | Full stressed drawdown |
|---|---|---:|---:|---:|---:|---:|
| EURUSD | M1 sweep/reclaim | EUR144.30 | EUR-100.23 | EUR134.49 | EUR44.08 | EUR174.59 |
| GBPUSD | cash; no eligible earlier candidate | - | - | - | - | - |
| NZDUSD | cash; no eligible earlier candidate | - | - | - | - | - |
| USDCHF | M5 sweep + M1 confirm | EUR27.92 | EUR-117.70 | EUR6.53 | EUR-89.78 | EUR236.25 |

Earlier: 2025-09-01 to2026-03-01 exclusive. Later: 2026-03-02 to2026-11-11 exclusive, with one calendar day between. Separate earlier/later accounts each start flat and cannot be summed to reconstruct the continuous full account.

## Every prototype, including rejected candidates

| Pair | Entry | Full normal / stressed net | Stressed drawdown | Trades normal/stressed | EUR100-200 net winners normal/stressed | Mean initial price risk normal/stressed |
|---|---|---:|---:|---:|---:|---:|
| EURUSD | M1 sweep/reclaim | EUR134.49 / EUR44.08 | EUR174.59 | 23 / 23 | 0 / 0 | EUR37.45 / EUR38.35 |
| EURUSD | M1 EMA reclaim | EUR-94.34 / EUR-289.65 | EUR316.56 | 37 / 37 | 0 / 0 | EUR38.36 / EUR39.26 |
| EURUSD | M5 sweep + M1 confirm | EUR-247.24 / EUR-439.05 | EUR475.66 | 36 / 36 | 1 / 1 | EUR36.15 / EUR37.05 |
| GBPUSD | M1 sweep/reclaim | EUR-553.64 / EUR-1,021.19 | EUR1,091.82 | 88 / 88 | 2 / 1 | EUR36.99 / EUR37.90 |
| GBPUSD | M1 EMA reclaim | EUR-250.39 / EUR-783.38 | EUR899.85 | 100 / 100 | 4 / 3 | EUR36.06 / EUR36.96 |
| GBPUSD | M5 sweep + M1 confirm | EUR-627.38 / EUR-873.91 | EUR1,131.13 | 47 / 47 | 0 / 0 | EUR39.48 / EUR40.38 |
| NZDUSD | M1 sweep/reclaim | EUR-155.89 / EUR-225.72 | EUR242.59 | 13 / 13 | 0 / 0 | EUR38.19 / EUR39.09 |
| NZDUSD | M1 EMA reclaim | EUR-98.35 / EUR-183.19 | EUR199.51 | 16 / 16 | 0 / 0 | EUR34.81 / EUR35.71 |
| NZDUSD | M5 sweep + M1 confirm | EUR-157.82 / EUR-243.56 | EUR332.53 | 16 / 16 | 0 / 0 | EUR37.20 / EUR38.10 |
| USDCHF | M1 sweep/reclaim | EUR-365.13 / EUR-494.31 | EUR494.31 | 25 / 25 | 1 / 0 | EUR45.85 / EUR46.93 |
| USDCHF | M1 EMA reclaim | EUR-363.22 / EUR-466.67 | EUR553.58 | 26 / 26 | 1 / 0 | EUR47.02 / EUR48.10 |
| USDCHF | M5 sweep + M1 confirm | EUR6.53 / EUR-89.78 | EUR236.25 | 17 / 17 | 0 / 0 | EUR43.30 / EUR44.38 |

All trades, losses and target-band counts use net results after modeled costs. Drawdown includes M1-close open P&L, incurred entry fees and actual simulated exit fills; intrabar/tick drawdown can be greater.

## Entry definitions and unchanged controls

All models use M1 decisions, completed M5 EMA20/EMA50 trend and EMA20 slope over3 prior M5 bars. Confirming M1 body is at least60% of range and range at least1.2 times the preceding20-range mean. Sweep penetration exceeds0.2 pip. Spread cap is0.7 pip.

- M1 sweep/reclaim: prior M1 sweeps12 earlier M1 extrema and closes back inside; the current directional candle confirms beyond that sweep candle's opposite edge.
- M1 EMA reclaim: prior M1 sweeps4 earlier extrema and closes against the M5 trend across M1 EMA20; current M1 reclaims EMA20 and the prior candle's opposite edge.
- M5 sweep/M1 confirm: latest completed M5 sweeps12 prior M5 extrema and reclaims them; M1 then confirms beyond its preceding2 extrema while that setup remains the latest closed M5, within1-5 minutes. One entry confirmation per sweep.

Initial SL is behind the swept/last5 M1 extreme with0.2-pip padding. Raw bid-close structure distance must be6-15 pips; rejected stops are not widened to meet a preferred distance. Lots are sized on the actual adverse filled entry-to-stop distance, including spread/slippage. Initial target remains2R, trailing activates1.5R with1R gap and removes TP at activation. Existing stops never move farther away.

Initial price-risk budget<=0.75%, original0.5-lot ceiling,0.75% aggregate exposure,EUR150 daily trigger and single-position rule. Original3600-second cooldown retained. Tight structural stops can use LESS than0.75% because lot ceiling is unchanged; actual utilization is disclosed. No widened existing stops or averaging/martingale.

The risk percentage is a maximum, not a promise that every position uses the full budget. The actual average initial risk in the table makes volume-ceiling effects explicit. Fees/gaps can add to a price-stop loss. Historical margin requirements and changing EUR conversions are not reconstructed.

Both directions retain the30-minute cap, daytime UTC entries05:00-18:00 intersected with existing sessions, and flat-by19:00 policy. Original3600-second cooldown is retained. Swap stays actively modeled and every position is audited against both rollover clocks; all48 accounts have zero swap, zero overnight positions and zero late exits.

## Costs, evidence and limitations

Normal: observed M1 historical spreads,1-pip fallback, EUR3.50 commission/lot/side and0.2-pip adverse market/stop slippage. Stress doubles commission/slippage and negative swap debits while preserving positive credits; fallback spread becomes2 pips. Observed spreads are not doubled. TP-limit exits have no exit slippage. These remain declared cost assumptions, not a broker invoice.

The same four histories, per-pair constant EUR tick valuations and financing snapshot as the previous scalp study are used. NZDUSD limits the common comparison to September2025 onward. Current swap rates are held constant with the prior explicit Wednesday triple-day assumption, but financing is zero in all observed paths under both GMT+3 and GMT+2 audit schedules.

There is no parameter grid, pair-specific tuning or post-result change to entry thresholds. These prices and dates were examined repeatedly in prior research; the later period is not an untouched holdout. Candidate counts are small and disclosed. Full ranking is descriptive; earlier profit alone cannot establish reliability. Source OHLC cannot reconstruct tick-level spread/latency/liquidity or all historical broker stop/margin constraints.

Pure signal definitions contain no broker calls and can be reused by a future live adapter, but current dispatch is offline only and requires explicit history. The research configuration is not an enabled production strategy. Existing entry/exit risk and cost code is shared.

## Validation and reproduction

**391 passed, one existing expected failure.** New tests cover each setup on BUY/SELL, future-bar invariance, M5-close ordering, insufficient displacement/structural width, immutable structural protection, offline-only guards, decision-clock validation, earlier-only/cash nomination and cached-vs-full replay equality for final/time/daily/stop exits in both directions.

Only entry feature construction is skipped on no-signal minutes. Every open-position M1 bar is still processed for SL/TP, financing, daily protection and elapsed exits; the regression comparison verifies identical trades and balances with this optimization disabled. Independent report audit reconciles all48 trade/cost ledgers, target-band counts, lot ceilings and per-entry0.75% price-risk bounds.

The frozen plan records all hypotheses, reference/history/source digests, precise settings and selection rules. Keep the original source commit and use a new output directory after changing source or assumptions. No bot was started and no order was placed.

The original capped study source is preserved at commit `3449655`; the later sizing supplement does not rewrite its trading outcomes.
