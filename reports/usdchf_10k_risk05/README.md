# USDCHF: matched EUR10,000, risk0.5%, trailing1.5R

Two frozen protocols: **24 matched old-path accounts** and **18 separate new-entry accounts**. Full period2024-11-15 to2026-11-11 exclusive. No monthly resets. All results include modeled spread, commission, slippage and financing.

## Original versus SELL pre-rollover flattening

Primary GMT+3 clock; read the clock/cost limitations in the full report.

| Old entry path | Normal net | Stressed net | Stressed sampled drawdown | EUR100-200 net winners normal/stressed |
|---|---:|---:|---:|---:|
| Original M30/M1 | EUR622.70 | EUR-266.22 | EUR644.95 | 15 / 15 |
| SELL flat before rollover | EUR503.29 | EUR74.67 | EUR496.72 | 13 / 10 |

Original earns more under normal costs; SELL flattening preserves a small positive net under stress. Both clock assumptions agree on those stressed profitability signs. [Full matched comparison](legacy/README.md).

## New entry tests remain separate

All three new M1/M5 USDCHF prototypes lost money under normal and stressed full-period costs. No positive participating earlier candidate qualified; the frozen nomination is cash. [Full new-entry tests](fast_entries/README.md).

The historical broker swap snapshot is held constant across the test. This is not actual daily historical financing. Stress doubles commission, slippage and negative swap debits; positive credits and observed historical spreads remain unchanged. Constant EUR valuation, reused dates, minute/tick limitations and unmodeled margin are disclosed in each report.

**397 tests passed; one existing expected failure.** Four new cases verify matched funding/risk/trailing, paired-old-task equivalence and actual BUY/SELL entry risk nearEUR50 rather than the earlier0.75% budget. All42 independent ledgers, costs, swap cash flows, risk bounds and target-band counts reconcile.

```powershell
python -m src.tools.research_usdchf_risk05 --history history/mt5_20261111/USDCHF_extended.json --output reports/usdchf_10k_risk05 --workers 6
```

Plans were frozen before results. Source/history/snapshot metadata and all trade ledgers are retained under each group; use a new output directory after source/protocol changes. No bot was started, no orders were placed and no live settings were changed.
