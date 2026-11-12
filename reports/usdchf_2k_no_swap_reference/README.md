# USDCHF M30/M1 — EUR2,000, 0.75%, trailing at 1.5R

**Status: reference replay completed; broker-swap comparison pending a connected MT5 session.**
The terminal journal reported `Invalid account`, Python reported `Authorization failed`, and the UI showed `0 / 0 Kb`. Algo Trading was disabled. No bot was started and no order was submitted. A saved account title is not evidence of an authenticated broker connection. No account identifiers or credentials are included here.

These results **exclude swap** and must not be described as a completed financing-inclusive test.

| Continuous test account | Net after spread, commission and slippage | Ending balance | Largest sampled equity decline | Trades | Average net winning trade | Winners EUR100–200 |
|---|---:|---:|---:|---:|---:|---:|
| Normal costs | +EUR276.61 | EUR2,276.61 | EUR156.26 | 150 | EUR24.26 | 0 |
| Doubled commission/slippage | +EUR95.68 | EUR2,095.68 | EUR162.10 | 148 | EUR21.97 | 0 |

Full period: **2024-11-15 00:00 UTC to 2026-11-11 00:00 UTC, exclusive**. Each scenario starts once at EUR2,000, with no monthly reset. Drawdown includes open positions at observed M1 closes and actual simulated exit fills; unknown intrabar extremes can be larger. The largest winning trade was EUR72.85 under normal costs and EUR61.64 under stressed costs. **The EUR100–200 winning-trade objective was not achieved.** Lots remain risk-derived; planned initial risk is EUR15 at the starting balance.

| Separate period (independent EUR2,000 start) | Normal net | Stressed net |
|---|---:|---:|
| Earlier: 2024-11-15 to 2025-11-15 exclusive | -EUR18.63 | -EUR37.53 |
| Later: 2025-11-16 to 2026-11-11 exclusive | +EUR300.77 | +EUR158.45 |

Separate period returns cannot be added to reproduce the full continuous account. The dates have been used repeatedly in earlier research; they are not an untouched holdout. This is a fixed-candidate replay, not a new walk-forward parameter selection or evidence of future profitability.

Settings: spread cap 0.9 pips, initial stop 20 pips, initial target 2R, trailing activation 1.5R, trailing gap 1R, target removed upon activation. Capital and entry risk are the user's newly requested EUR2,000 and 0.75%. Paper aggregate exposure cap is aligned from 0.5% to 0.75% so the requested entry is possible. The existing EUR150 daily trigger, single-position logic and other protections remain. Live settings are untouched.

Normal assumptions: observed historical spread (1-pip fallback), EUR3.50 commission per lot per side, 0.2-pip adverse market/stop slippage. Stress: EUR7 and 0.4 pip; observed spread unchanged, missing-spread fallback 2 pips. No slippage on take-profit limit fills. Existing history uses constant tick valuation interpreted in EUR, as in prior research. Margin requirements and full tick paths are not reconstructed.

## Financing implementation and remaining test

The new offline `SwapModel` books signed financing at rollover before risk decisions, includes Wednesday triple financing and leaves weekend weights at zero. Financing affects subsequent risk sizing and the daily loss guard; cash flows are not charged twice at exit. The stressed model doubles swap **debits** while keeping credits unchanged. Modes requiring unavailable currency or interest conversions are rejected.

Once actual metadata is available, the runner compares normal/stressed costs with and without swap, using broker midnight GMT+3 and GMT+2 sensitivity across all three periods. Current rates will be clearly labeled as constant assumptions across historical dates; they do not reconstruct historical broker rate changes. [MT5 swap documentation](https://www.mql5.com/en/book/automation/symbols/symbols_swaps) defines the supported rate units. [TradeQuo trading regulations, section 5.1](https://www.tradequo.com/wp-content/uploads/2022/10/regulations_for_trading_operations.pdf) describe overnight financing and triple Wednesday rollover.

Read-only metadata capture, with MT5 already running, connected and Algo Trading disabled:

```powershell
python -m src.tools.capture_swap_snapshot --output history/mt5_20261111/USDCHF_swap_snapshot_20261112.json
```

Then run the offline comparison (no broker connection or trading API is available inside research workers):

```powershell
python -m src.tools.research_swap_2k --history history/mt5_20261111/USDCHF_extended.json --snapshot history/mt5_20261111/USDCHF_swap_snapshot_20261112.json --output reports/usdchf_2k_swap --workers 3
```

The reference registration records the execution-time source digest. Notification settings and local runtime paths were removed from the publication copy after replay; risk assumptions and outcomes are unchanged. The subsequent metadata-export helper and runtime publication filtering do not alter this reference's signal, fill or sizing logic.

Validation: 316 passed, one existing expected failure. Twelve new swap tests cover signed debits/credits, stressed debits, Wednesday/weekend schedule, time zones, exact-entry boundary, idempotence, unit conversion, unsupported modes, realized drawdown, final liquidation accounting and daily-loss liquidation. All use synthetic bars; no broker orders.
