# EUR20k USDCHF paper sizing: EUR100-200 successful trades

**Simulation only. No live risk/capital/lot setting changed.**

| Risk budget | Mean winner EUR | Mean loser EUR | Mean all EUR | Wins EUR100-200 | Total trades | Year net EUR | Realized DD EUR | Earlier-year net EUR |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.1% | 25.29 | -19.69 | 2.33 | 0 | 143 | 332.69 | 157.21 | -465.90 |
| 0.2% | 50.58 | -39.39 | 4.65 | 11 | 143 | 665.38 | 314.41 | -922.26 |
| 0.3% | 75.99 | -59.24 | 6.96 | 14 | 143 | 994.62 | 471.62 | -1397.83 |
| 0.5% | 122.96 | -99.46 | 9.39 | 17 | 141 | 1323.32 | 797.56 | -2269.33 |

Starting equity EUR20,000; max lot ceiling raised from 0.05 to 0.5; declared risk 0.1/0.2/0.3/0.5%. No live settings changed.

Same USDCHF M30/M1 signals, stop, target, trailing, sessions, cooldown, one-position rule, EUR150 daily guard and 0.5% portfolio exposure guard. Position size remains risk-derived; no loss chasing or stop widening.

Twelve monthly tests: 16 November 2025 to 11 November 2026 exclusive. Earlier year: 15 November 2024 to 15 November 2025 exclusive. Every replay starts at EUR20,000. Base costs: observed spread, EUR3.50/lot/side commission, 0.2-pip adverse market/stop slippage. Earlier year and later six tests are also replayed with EUR7.00 commission and 0.4-pip slippage; observed spreads unchanged, missing-spread fallback doubled. Detailed distributions, extreme wins/losses and cost-stress results are retained in report.json.

- Previously examined history, not untouched evidence or a guarantee of future profits.
- Monthly tests reset flat at EUR20,000; no continuous compounding. Realized drawdown omits intratrade equity fluctuations.
- Historical spreads; assumed commission/slippage and constant valuation. Swap/overnight financing and full tick/latency effects excluded.
- EUR150 daily guard is a trigger, not a guaranteed maximum day loss; fills and gaps can exceed it.
- Profit from a successful trade does not mean profit from every trade or positive long-term expectancy. Earlier losing-year and cost-stress results are retained.
- No bot started, broker connected or orders placed.

Reproduce: `python -m src.tools.research_capital_20k`
