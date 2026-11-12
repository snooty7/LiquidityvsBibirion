# Matched old USDCHF paths: EUR10,000, risk0.5%, trailing1.5R

Only one trading rule differs: original positions can remain overnight; the other path closes **SELL only** before rollover. BUY retains the original overnight behavior. Entry signals, capital, percentage risk, size ceiling, stop/target/trailing, sessions, cooldown and cost assumptions are otherwise identical.

In the primary GMT+3 scenario, the original earns more under normal costs, but SELL pre-rollover flattening is the only positive path under stressed costs. This is a paired replay, not proportional scaling of an older EUR20,000 no-swap result.

## Primary full-period comparison

| Variant | Costs including swap | Net profit | Ending equity | Sampled equity drawdown | Net winners EUR100-200 / all trades | Signed net swap |
|---|---|---:|---:|---:|---:|---:|
| Original M30/M1 | Normal | EUR622.70 | EUR10,622.70 | EUR516.99 | 15 / 150 | EUR-312.56 |
| Original M30/M1 | Stressed | EUR-266.22 | EUR9,733.78 | EUR644.95 | 15 / 148 | EUR-658.21 |
| SELL flat before rollover | Normal | EUR503.29 | EUR10,503.29 | EUR481.72 | 13 / 159 | EUR42.77 |
| SELL flat before rollover | Stressed | EUR74.67 | EUR10,074.67 | EUR496.72 | 10 / 158 | EUR41.68 |

SELL flattening reduces normal net by EUR119.41 versus original, but improves stressed net by EUR340.89 and reduces stressed sampled drawdown by EUR148.23. These figures refer to GMT+3 only; both clocks are reported below. Financing differences need not equal net-profit differences because early exits, sizing and daily protection can change the trade path.

## Clock sensitivity and separate windows

| Variant | Broker clock | Earlier normal / stressed net | Later normal / stressed net | Full normal / stressed net | Full stressed drawdown |
|---|---|---:|---:|---:|---:|
| Original M30/M1 | GMT+3 | EUR-107.54 / EUR-223.82 | EUR712.75 / EUR10.91 | EUR622.70 / EUR-266.22 | EUR644.95 |
| Original M30/M1 | GMT+2 | EUR-101.41 / EUR-211.55 | EUR758.98 / EUR87.38 | EUR673.19 / EUR-158.73 | EUR605.09 |
| SELL flat before rollover | GMT+3 | EUR-79.02 / EUR-153.42 | EUR584.54 / EUR224.93 | EUR503.29 / EUR74.67 | EUR496.72 |
| SELL flat before rollover | GMT+2 | EUR-61.63 / EUR-136.04 | EUR728.67 / EUR353.79 | EUR666.17 / EUR227.39 | EUR489.41 |

The original is stressed-negative under both clocks. SELL flattening is stressed-positive under both clocks, but the remaining profit is modest. No clock was chosen retrospectively for better returns.

SELL positions close at the first available M1 opening quote at/after23:55 broker time; SELL entries are blocked from that deadline until midnight. Missing quotes do not create a fictional earlier fill: any incurred financing is retained. BUY remains unchanged, so positive BUY swap can remain in this path. The existing0.5-lot ceiling is nonbinding at most old-model entries and risk still derives from the20-pip initial structure/protection.

## Shared funding, data and cost assumptions

Instrument USDCHF (broker USDCHF-). **EUR10,000 initial equity, risk ceiling0.5% of current simulated equity**, approximately EUR50 initial price-risk budget. Original trailing activation1.5R/gap1R and initial2R target retained. Fees and gaps can add to the price-stop loss.

Full period: **2024-11-15 00:00 UTC to2026-11-11 00:00 UTC exclusive** (through10 November2026 inclusive). Earlier:2024-11-15 to2025-11-15 exclusive; later:2025-11-16 to2026-11-11 exclusive. Each window is an independent continuous account with no monthly reset. Earlier/later nets cannot be added to reproduce full compounding and position carry.

Normal costs: observed historical spread,1-pip missing-spread fallback, EUR3.50/lot/side commission and0.2-pip adverse market/stop slippage. Stress: EUR7,0.4 pip and double negative swap debits; positive credits unchanged. Observed spreads are not doubled; missing-spread fallback becomes2 pips. No adverse exit slippage on TP-limit fills.

Swap is actively modeled at rollover. The saved12-November2026 broker snapshot is held constant over history, using the historical EUR tick valuation. It is not a reconstruction of changing daily historical financing. Invalid MT5 triple-day code7 requires the explicit prior Wednesday-triple assumption. Primary broker midnight is fixed GMT+3, with GMT+2 sensitivity; historical DST/clock policy is unknown.

Both groups retain0.5% aggregate exposure cap, EUR150 daily trigger, single-position rule and original cooldown. Drawdown includes open P&L at observed M1 closes, incurred entry fees, financing cash flows and simulated fills; intrabar/tick losses can be larger. Capital/risk are identical in both groups, but entry definitions and initial stop structures differ in the new-entry group.

No martingale, averaging, grid or widening an already-tightened stop. Historical margin, latency, true tick spreads/liquidity, changing conversion rates and broker stop constraints are not reconstructed. Dates and prior outcomes were examined repeatedly; these are exploratory historical tests, not untouched holdout evidence or live profitability guarantees.

See [separate M1/M5 tests](../fast_entries/README.md). They are not part of this old-path ranking.

Validation: all24 account/cost/financing ledgers and every0.5% entry-risk budget reconcile. The paired-task regression verifies that only the label and SELL overnight policy differ. No live settings changed, bot started or order placed.
