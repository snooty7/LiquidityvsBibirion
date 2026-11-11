# USDCHF M30/M1: one same-level re-entry test

Virtual EUR 10,000 per monthly window. Risk 0.1%, max lot 0.05, same stops, trailing and daily/exposure guards.

| Model | Net after modeled costs EUR | Max realized drawdown EUR | Blocked entries |
|---|---:|---:|---:|
| baseline | 147.86 | 69.87 | 0 |
| reentry | 147.86 | 69.87 | 0 |

Rule: After a successful simulated entry, block a new entry in the same direction within 6 pips of its setup level when the new setup candle is <=2 M30 bars after the previous executed setup candle. Opposite direction passes. Existing one-hour cooldown stays unchanged.

Twelve 30-day windows: 16 November 2025 to 11 November 2026 exclusive. Native saved history only. Historical spread, EUR 3.50/lot/side assumed commission, 0.2-pip adverse market/stop slippage. Later-six doubled commission/slippage results are in report.json.

- Previously examined dates; not untouched validation.
- Monthly windows reset flat; no compounding; realized drawdown excludes intratrade equity swings.
- Swap/overnight financing excluded; commission/slippage assumed and symbol valuation held constant.
- Research-only paper-entry hook; no live implementation or active setting change. Its blocked entries are counted separately from the generic replay risk-skip counter.
- No bot started, broker connected or orders sent. No live settings changed.

Reproduce: `python -m src.tools.research_reentry`
