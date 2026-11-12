# Separate new M1/M5 USDCHF entries: EUR10,000, risk0.5%

These new entry prototypes are evaluated separately from the old M30/M1 comparison. Definitions and thresholds are unchanged from the preceding new-entry research; funding and risk are now matched to the requested EUR10,000/0.5% and the same full two-year USDCHF history.

**No candidate had positive earlier stressed performance with trading participation. The registered selection therefore chose cash.** All three prototypes were nevertheless replayed on later/full data and both cost levels; cash fallback is not used to conceal their losses.

## Every prototype, full period

| New entry | Normal net | Stressed net | Stressed sampled drawdown | Trades normal/stressed | Net winners EUR100-200 normal/stressed | Mean initial price risk normal/stressed |
|---|---:|---:|---:|---:|---:|---:|
| M1 sweep/reclaim | EUR-453.49 | EUR-574.51 | EUR574.51 | 25 / 25 | 0 / 0 | EUR48.16 / EUR47.88 |
| M1 EMA reclaim | EUR-344.48 | EUR-439.46 | EUR581.08 | 26 / 26 | 0 / 0 | EUR48.09 / EUR47.91 |
| M5 sweep + M1 confirm | EUR-2.92 | EUR-110.01 | EUR279.42 | 17 / 17 | 0 / 0 | EUR49.85 / EUR49.55 |

## Earlier selection and later validation

| Entry | Earlier normal / stressed net | Earlier executed trades | Earlier confirmed raw setups | Later normal / stressed net |
|---|---:|---:|---:|---:|
| M1 sweep/reclaim | EUR-108.76 / EUR-117.71 | 2 | 55 | EUR-344.58 / EUR-459.85 |
| M1 EMA reclaim | EUR-53.28 / EUR-29.73 | 3 | 79 | EUR-289.48 / EUR-411.60 |
| M5 sweep + M1 confirm | EUR0.00 / EUR0.00 | 0 | 29 | EUR-2.92 / EUR-110.01 |

Zero earlier M5-sweep P&L means no executed trades in that window, not a demonstrated break-even strategy. Confirmed raw setups can still be rejected by the entry/risk/session/spread guards. No prototype is substituted after looking at later results.

Pure signals use completed M1/M5 bars: M5 EMA20/50 direction and prior slope, liquidity sweeps/reclaims and directional M1 displacement. M1 bodies must be>=60% of their range; range>=1.2 times the preceding20 M1 mean. Sweep penetration>0.2 pip. Spread cap0.7 pip. Structural initial SL behind the swept/last5 M1 extreme with0.2-pip padding, accepting6-15 raw pips. Initial2R target, trailing1.5R/gap1R. Full0.5% risk sizing uses the recorded broker volume ceiling, not a fixed lot. Old-path sizing ceiling is different, so these remain separate prototype bundles.

Both directions use the30-minute cap, weekday05:00-18:00 UTC entries intersecting original sessions, and flat by19:00 UTC. Financing remains active as an audit; all18 paths have zero swap, no overnight positions and no late exits under both rollover-clock audits. Existing SL/TP and daily protection have priority; no stop is widened.

## Shared funding, data and cost assumptions

Instrument USDCHF (broker USDCHF-). **EUR10,000 initial equity, risk ceiling0.5% of current simulated equity**, approximately EUR50 initial price-risk budget. Original trailing activation1.5R/gap1R and initial2R target retained. Fees and gaps can add to the price-stop loss.

Full period: **2024-11-15 00:00 UTC to2026-11-11 00:00 UTC exclusive** (through10 November2026 inclusive). Earlier:2024-11-15 to2025-11-15 exclusive; later:2025-11-16 to2026-11-11 exclusive. Each window is an independent continuous account with no monthly reset. Earlier/later nets cannot be added to reproduce full compounding and position carry.

Normal costs: observed historical spread,1-pip missing-spread fallback, EUR3.50/lot/side commission and0.2-pip adverse market/stop slippage. Stress: EUR7,0.4 pip and double negative swap debits; positive credits unchanged. Observed spreads are not doubled; missing-spread fallback becomes2 pips. No adverse exit slippage on TP-limit fills.

Swap is actively modeled at rollover. The saved12-November2026 broker snapshot is held constant over history, using the historical EUR tick valuation. It is not a reconstruction of changing daily historical financing. Invalid MT5 triple-day code7 requires the explicit prior Wednesday-triple assumption. Primary broker midnight is fixed GMT+3, with GMT+2 sensitivity; historical DST/clock policy is unknown.

Both groups retain0.5% aggregate exposure cap, EUR150 daily trigger, single-position rule and original cooldown. Drawdown includes open P&L at observed M1 closes, incurred entry fees, financing cash flows and simulated fills; intrabar/tick losses can be larger. Capital/risk are identical in both groups, but entry definitions and initial stop structures differ in the new-entry group.

No martingale, averaging, grid or widening an already-tightened stop. Historical margin, latency, true tick spreads/liquidity, changing conversion rates and broker stop constraints are not reconstructed. Dates and prior outcomes were examined repeatedly; these are exploratory historical tests, not untouched holdout evidence or live profitability guarantees.

All18 ledgers and per-entry0.5% risk budgets reconcile. Pure signal definitions are broker independent; current dispatch is offline only. No production mode or live setting is enabled. Earlier-only nomination was locked before later/full new-entry outcomes.

See [matched old paths](../legacy/README.md) for the original-versus-SELL comparison; these groups are not combined into a retrospective winner selection.
