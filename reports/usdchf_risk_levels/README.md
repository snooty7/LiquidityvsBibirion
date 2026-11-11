# USDCHF: larger risk budgets with fixed protection caps

**Applied to offline simulations only. No live risk level selected; active configurations unchanged.**

Declared budgets are 0.1%, 0.2%, 0.3% and 0.5%. All keep the 0.05 maximum lot, original initial stop/exits, daily loss limit and portfolio cap. Results come from full replays, not multiplied past P&L.

**Budgets of 0.2%, 0.3% and 0.5% produce identical outcomes in this study because the lot cap binds.**

## Twelve monthly test windows

Each window starts flat with EUR 10,000; summed monthly returns are not continuous compounding. Both references and these dates were already observed before this sizing study.

| Reference | Declared risk % | Volumes (lot: trades) | Maximum actual initial risk % | Net EUR | Realized DD EUR | Longest losing run | Worst losing-run loss EUR |
|---|---:|---|---:|---:|---:|---:|---:|
| baseline | 0.1 | 0.04: 143 | 0.0879 | 147.86 | 69.87 | 6 | 54.67 |
| baseline | 0.2 | 0.05: 143 | 0.1100 | 184.83 | 87.34 | 6 | 68.34 |
| baseline | 0.3 | 0.05: 143 | 0.1100 | 184.83 | 87.34 | 6 | 68.34 |
| baseline | 0.5 | 0.05: 143 | 0.1100 | 184.83 | 87.34 | 6 | 68.34 |
| spread_0_9 | 0.1 | 0.04: 141 | 0.0879 | 148.81 | 69.87 | 6 | 54.67 |
| spread_0_9 | 0.2 | 0.05: 141 | 0.1100 | 186.02 | 87.34 | 6 | 68.34 |
| spread_0_9 | 0.3 | 0.05: 141 | 0.1100 | 186.02 | 87.34 | 6 | 68.34 |
| spread_0_9 | 0.5 | 0.05: 141 | 0.1100 | 186.02 | 87.34 | 6 | 68.34 |

Actual initial risk is entry-to-stop price exposure against each replay's entry equity, excluding commissions, exit slippage and gaps. It is not a maximum possible loss. Streaks across monthly resets are descriptive; per-replay streaks are retained in report.json.

## Earlier losing year and cost stress

The earlier year is a separate continuous replay, 15 November 2024 to 15 November 2025 exclusive. It is not an overlapping sum of training windows. Later-six results cover 15 May to 11 November 2026 exclusive.

| Reference | Budget % | Earlier net EUR | Earlier DD EUR | Earlier stressed net EUR | Later-six net EUR | Later-six stressed net EUR |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 0.1 | -212.72 | 272.76 | -298.54 | 93.87 | 66.33 |
| baseline | 0.2 | -265.90 | 340.95 | -373.17 | 117.33 | 82.92 |
| baseline | 0.3 | -265.90 | 340.95 | -373.17 | 117.33 | 82.92 |
| baseline | 0.5 | -265.90 | 340.95 | -373.17 | 117.33 | 82.92 |
| spread_0_9 | 0.1 | -52.69 | 66.49 | -61.82 | 87.37 | 59.92 |
| spread_0_9 | 0.2 | -65.86 | 83.11 | -77.27 | 109.22 | 74.91 |
| spread_0_9 | 0.3 | -65.86 | 83.11 | -77.27 | 109.22 | 74.91 |
| spread_0_9 | 0.5 | -65.86 | 83.11 | -77.27 | 109.22 | 74.91 |

Increasing position size scales losing periods too; it does not establish a stronger entry edge. A positive later test year cannot erase the earlier-year evidence or justify live promotion.

## Protocol, protections and limitations

- USDCHF M30 setups, explicit M1 confirmation with 300-bar context. References: original spread cap 1.8 pips and previously tested tighter 0.9-pip cap.
- Max lot 0.05, 20-pip initial stop, same 2R initial target and 1R/1R trailing, EUR 150 daily limit with closing, 0.5% portfolio risk cap, one position, sizing/valuation guards, sessions and cooldown. Only configured risk_pct changes within each reference.
- The eight settings and windows were registered before replay; no risk budget is nominated for live use.
- Twelve nonoverlapping monthly tests, 16 November 2025 to 11 November 2026 exclusive; later six also replayed under cost stress.
- Observed spreads, assumed EUR 3.50/lot/side commission and 0.2-pip adverse market/stop slippage. Stress doubles commission/slippage to EUR 7.00 and 0.4 pip. Observed spreads stay unchanged; missing-spread fallback doubles from 1 to 2 pips.
- **Swap/overnight financing is not included.** This study isolates sizing while preserving prior cost comparability.
- Realized cash-flow drawdown is not intratrade equity drawdown or a future loss bound.
- The two references were selected because their previously examined historical test results were positive. This is sizing sensitivity on reused history, not evidence of a new edge or unseen validation.
- The earlier year is one continuous replay, not overlapping training sums. It is reported separately and must not be hidden by the later positive test year.
- Monthly folds each restart flat at EUR 10,000. Summed returns and drawdown are descriptive, not a continuously compounded account or a guaranteed income.
- Historical spreads, assumed commissions/slippage, constant historical valuation. Swap/overnight financing, full tick paths and latency are not modeled. Changing only sizing preserves comparability with prior reference reports.
- Higher risk budgets do not improve entry expectancy; realized losses and drawdowns can grow. No lot cap, stop, daily or portfolio protection is relaxed.
- Saved history only. Broker connections and order methods are blocked. No bot started, no trades placed, no active configuration changed.

## Reproduce and audit

```powershell
.\.venv\Scripts\python.exe -m src.tools.research_risk_levels --workers 6
.\.venv\Scripts\python.exe -m src.tools.render_risk_levels reports/usdchf_risk_levels/report.json
```

plan.json freezes configuration and data/code hashes. report.json contains all 160 replay rows and five scope summaries per configuration. trades.json contains all saved simulated fills; audit.json reconstructs entry equity, risk, costs, drawdown and loss streaks.
