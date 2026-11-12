# USDCHF M30/M1 — completed financing-inclusive EUR10,000 replay

**Conclusion: positive at normal modeled costs, negative at doubled commission/slippage/swap debits. The candidate fails the cost-resilience objective.** All 18 independent replays completed; no parameter search or strategy change followed their outcomes.

Capital EUR10,000; risk 0.75% per entry (EUR75 initial price-risk budget), trailing activation 1.5R and gap 1R. Full continuous period: **2024-11-15 00:00 UTC to 2026-11-11 00:00 UTC exclusive**. Each account starts once, without monthly resets.

## Main results: assumed broker midnight GMT+3

| Costs, including swap | Net profit | Ending equity | Largest sampled equity drawdown | Trades | Net winners EUR100–200 | Winners above EUR200 | Mean net winner |
|---|---:|---:|---:|---:|---:|---:|---:|
| Normal | EUR796.12 | EUR10,796.12 | EUR774.93 | 148 | 23 | 8 | EUR118.12 |
| Stressed | EUR-465.41 | EUR9,534.59 | EUR961.06 | 146 | 17 | 7 | EUR105.53 |

Drawdown includes open P&L at observed M1 closes, incurred entry fees and financing cash flows, plus simulated exit fills. Intrabar/tick drawdown can be larger. Target counts use **net profit after all modeled costs**, inclusive EUR100–200; total account profit includes every losing trade.

## Clock sensitivity and reference without financing

Historical broker clock/DST policy was not reconstructed. The alternative fixed GMT+2 clock also fails stressed profitability. No clock was selected using its result.

| Scenario | Net profit | Largest sampled drawdown | Net winners EUR100–200 | Trades | Signed net swap |
|---|---:|---:|---:|---:|---:|
| GMT+3 normal | EUR796.12 | EUR774.93 | 23 | 148 | EUR-433.24 |
| GMT+3 stressed | EUR-465.41 | EUR961.06 | 17 | 146 | EUR-906.42 |
| GMT+2 normal | EUR855.92 | EUR777.49 | 23 | 148 | EUR-368.39 |
| GMT+2 stressed | EUR-320.87 | EUR901.22 | 17 | 145 | EUR-783.66 |
| No swap, normal reference | EUR1,241.48 | EUR795.91 | 25 | 148 | EUR0.00 |
| No swap, stressed reference | EUR527.96 | EUR840.55 | 21 | 145 | EUR0.00 |

## Separate earlier and later accounts

| Independent EUR10,000 account | GMT+3 normal net | GMT+3 stressed net | GMT+2 normal net | GMT+2 stressed net |
|---|---:|---:|---:|---:|
| 2024-11-15 to 2025-11-15 exclusive | EUR-98.10 | EUR-266.04 | EUR-88.90 | EUR-247.64 |
| 2025-11-16 to 2026-11-11 exclusive | EUR886.35 | EUR-174.63 | EUR951.64 | EUR-62.21 |

Separate-window returns cannot be summed to reproduce the full continuous account: sizing compounds and daily protection can change the trade sequence. Earlier and later dates were already examined in prior research; these are fixed-candidate historical replays, **not an untouched holdout or a new walk-forward selection**. No live profitability claim is made.

## Financing metadata and explicit assumptions

The read-only MT5 capture succeeded on 2026-11-12 at 06:55:29 UTC, with EUR account currency and Algo Trading disabled. It saved no account identifier, credentials or personal details. See [swap_snapshot.json](swap_snapshot.json). The instrument was USDCHF-, swap mode 1 (points), long +1.41113636 points and short -25.75364 points per lot/day.

For consistency with earlier replays, point rates are converted with the historical constant EUR tick valuation 1.0823916525955752 per 0.00001 price tick. This yields approximately **+EUR1.52740222 per lot/day long** and **-EUR27.87552496 per lot/day short**, before weekday weights. The freshly returned tick value was zero and was not used for sizing or to infer free financing. Current broker swap rates are held constant over the historical period; actual historical daily rates and changing EUR conversions are unavailable.

**Schedule exception:** MT5 returned swap_rollover3days=7, outside its documented Sunday=0 through Saturday=6 weekday enumeration. The code now rejects this value instead of modulo-wrapping it to Saturday. This study explicitly records `--triple-day 3`: Wednesday triple financing, Friday one day, weekend zero. The indexed [Quo Markets Regulations for Trading Operations, section 5.1.1](https://quomarkets.com/wp-content/uploads/2025/06/Regulations-for-Trading-Operations_QM_20250625.pdf) describes this Wednesday-to-Thursday schedule. The PDF URL returned 404 during direct retrieval; its indexed primary-source excerpt was available. This is a disclosed schedule assumption, not a verified per-symbol daily multiplier table. [MT5 documentation](https://www.mql5.com/en/docs/standardlibrary/tradeclasses/csymbolinfo/csymbolinfoswaprollover3days) identifies the returned value as a weekday enumeration.

Financing is booked at assumed broker midnight before subsequent bar-open risk checks. Entry exactly at rollover is exempt; an exit recorded at rollover before processing the next bar is exempt. These are deterministic minute-resolution conventions. Cash flows affect subsequent position sizing and daily protection, and are not charged again at exit. Net performance differences versus no-swap reference therefore need not equal the sum of swap alone.

Normal costs retain historical observed spread (1-pip fallback), EUR3.50/lot/side commission and 0.2-pip adverse market/stop slippage. Stress doubles commission to EUR7, slippage to 0.4 pip and **negative swap debits**; positive swap credits are unchanged. **Observed spreads are not doubled**; only the missing-spread fallback rises to 2 pips. Take-profit limit fills have no exit slippage.

Fixed controls remain: spread cap 0.9 pips, initial stop 20 pips, initial target 2R, trailing target removal at activation, max lot 0.5, risk-derived lots, EUR150 daily trigger and single-position logic. The paper exposure cap remains 0.75%, as already aligned to the requested entry risk. No active/live settings changed. Broker historical margin, changing stop-distance constraints, latency and full tick paths are not reconstructed.

## Reproduction and validation

```powershell
python -m src.tools.research_swap_2k --history history/mt5_20261111/USDCHF_extended.json --snapshot reports/usdchf_10k_swap/swap_snapshot.json --output reports/usdchf_10k_swap --capital 10000 --triple-day 3 --workers 4
```

The plan was frozen before outcomes, with history and source SHA-256 digests. After source changes, use a new output directory rather than amending a frozen plan. The report contains all 18 replay ledgers. Each worker forbids broker initialization and trading methods.

**329 tests passed; one existing expected failure.** Five added cases cover invalid triple-day codes, explicit documented overrides and correct weekday mapping. Existing regression coverage verifies risk-based sizing, daily protection, stop handling, signed swap, stressed debits, duplicate prevention, final liquidation, cash-flow drawdown and EUR10,000 capital propagation. Independent report checks reconciled every trade/cash-flow ledger, target-band count and ending balance; repeated no-swap results exactly match the previous EUR10,000 study.

No bot was started, no order was placed, and no live execution setting was changed.
