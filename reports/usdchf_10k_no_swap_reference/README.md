# USDCHF M30/M1 — EUR10,000, risk 0.75%, trailing activation 1.5R

**PARTIAL: actual offline reference replays completed, but swap-inclusive comparison is blocked by MT5 authorization. These results EXCLUDE swap.**

Metadata capture was attempted against the already-running terminal with trading calls prohibited. MT5 returned `(-6, Terminal: Authorization failed)`. The terminal journal also reported `Invalid account`. No swap snapshot was available. Rates were not fabricated. No bot or trading engine was started and no orders were submitted.

Each scenario was replayed from historical bars with EUR10,000 starting equity and risk-derived lots. These are new simulations, not five-times scaling of the EUR2,000 results.

Full continuous period: 2024-11-15 00:00 UTC to 2026-11-11 00:00 UTC exclusive. No monthly resets.

| Scenario (swap excluded) | Net profit | Ending equity | Largest M1-close equity drawdown | Trades | Net winners EUR100–200 | Net winners above EUR200 | Mean net winner |
|---|---:|---:|---:|---:|---:|---:|---:|
| Normal costs | EUR1,241.48 | EUR11,241.48 | EUR795.91 | 148 | 25 | 9 | EUR123.60 |
| Doubled commission/slippage | EUR527.96 | EUR10,527.96 | EUR840.55 | 145 | 21 | 9 | EUR116.55 |

Target-band counts include only individual closed trades with **net** profit between EUR100 and EUR200 inclusive; losses remain included in total account profit.

| Separate account window | Normal net | Stressed net |
|---|---:|---:|
| 2024-11-15 to 2025-11-15 exclusive | EUR-40.16 | EUR-135.80 |
| 2025-11-16 to 2026-11-11 exclusive | EUR1,302.01 | EUR656.48 |

Separate windows each start independently at EUR10,000; their profits cannot be added to reconstruct the continuously compounded full-period account. The older window loses money in both scenarios. These dates have already been examined in prior research and are not an untouched holdout. No parameter optimization or new walk-forward selection was performed.

Fixed settings: USDCHF M30 with M1 confirmation, spread cap 0.9 pips, 20-pip initial stop, 2R initial target, trailing activation 1.5R and gap 1R, target removed on activation, max lot 0.5. Initial risk budget is EUR75 (0.75%), position size rounded down to the allowed step. The existing EUR150 daily trigger and single-position logic remain; paper portfolio exposure cap stays 0.75%, as in the prior EUR2,000 study. No active/live configuration changed.

Costs: observed spreads, 1-pip fallback, EUR3.50/lot/side commission and 0.2-pip adverse market/stop slippage. Stress doubles commission and slippage to EUR7 and 0.4 pip; historical observed spreads stay unchanged and missing-spread fallback becomes 2 pips. Take-profit limit exits have no exit slippage.

Drawdown includes open P&L at observed M1 closes, entry fees and simulated exit fills. Intrabar/tick losses can be larger. Constant historical EUR tick valuation is retained; historical margin requirements, latency and full tick paths are not reconstructed. Positive results excluding financing do not establish positive results including financing or future profitability.

## Reproduce and finish

Reference replay:

```powershell
python -m src.tools.research_swap_2k --history history/mt5_20261111/USDCHF_extended.json --output reports/usdchf_10k_no_swap_reference --capital 10000 --baseline-only --workers 3
```

After MT5 is connected with Algo Trading disabled:

```powershell
python -m src.tools.capture_swap_snapshot --output history/mt5_20261111/USDCHF_swap_snapshot_20261112.json
python -m src.tools.research_swap_2k --history history/mt5_20261111/USDCHF_extended.json --snapshot history/mt5_20261111/USDCHF_swap_snapshot_20261112.json --output reports/usdchf_10k_swap --capital 10000 --workers 3
```

The financing run will book swap during the holding period, compare GMT+3 and GMT+2 rollover assumptions, and double negative swap debits while keeping positive credits unchanged under stress. Current broker rates will be labeled as constant historical assumptions, not reconstructed daily historical rates. Unsupported currency/interest conversions fail explicitly.

Validation: **324 passed, one existing expected failure**. Added coverage verifies that requested EUR10,000 capital reaches both replay and reports, rejects invalid capital, and checks EUR10,000 synthetic risk sizing, swap accounting, daily protection and drawdown without any broker orders.
