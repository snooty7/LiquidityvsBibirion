# Four-pair intraday scalping: EUR10,000, risk 0.75%, no swap

**No tested configuration was profitable after modeled costs.** All twelve pair/duration configurations lost money under both normal and stressed costs. The least negative normal result was GBPUSD/15 minutes (-EUR825.83); under stress it was NZDUSD/15 minutes (-EUR1,570.87). These are losses, not profitable winners.

**No-swap condition passed in all 48 accounts:** EUR0 financing, zero overnight positions and zero late exits. Nonzero broker swap rates remained active in the model; financing was not disabled or erased.

The user changed the scope from SELL-only overnight avoidance to scalping with no overnight positions on either side. This study therefore closes BUY and SELL after 15/30/60 minutes. It retains the existing M30 liquidity/M1 confirmation entry family; it is not a newly designed M1-only signal.

Common full period: **2025-09-01 00:00 UTC to 2026-11-11 00:00 UTC exclusive**, approximately 14 months. Every pair/duration/window starts independently at EUR10,000, risk 0.75%, with no monthly resets. Results cannot be added into a concurrently funded portfolio.

## Earlier-selected duration per pair

Earlier stressed net selected 15 minutes for each pair because it lost less during that earlier period. A negative nomination is not a profitability approval. All alternatives are also reported below.

| Pair / holding limit | Normal net | Normal drawdown | Stressed net | Stressed drawdown | EUR100-200 winners normal/stressed | Trades normal/stressed |
|---|---:|---:|---:|---:|---:|---:|
| EURUSD / 15min | EUR-1,129.86 | EUR1,156.95 | EUR-1,962.15 | EUR1,982.43 | 0 / 0 | 234 / 234 |
| GBPUSD / 15min | EUR-825.83 | EUR975.09 | EUR-1,661.69 | EUR1,742.85 | 0 / 0 | 226 / 226 |
| NZDUSD / 15min | EUR-856.05 | EUR862.71 | EUR-1,570.87 | EUR1,573.23 | 0 / 0 | 193 / 193 |
| USDCHF / 15min | EUR-1,523.77 | EUR1,538.73 | EUR-2,174.45 | EUR2,181.61 | 0 / 0 | 216 / 216 |

Returns are for the full period, not monthly or annual. Drawdown includes open P&L at observed M1 closes, incurred entry fees and simulated fills; tick/intrabar drawdown can be greater. Target-band counts use individual net profit inclusive EUR100-200. Account profit includes all losses.

## All twelve configurations

| Pair | Minutes | Normal / stressed net | Normal / stressed drawdown | EUR100-200 winners normal/stressed | Normal / stressed win rate |
|---|---:|---:|---:|---:|---:|
| EURUSD | 15 | EUR-1,129.86 / EUR-1,962.15 | EUR1,156.95 / EUR1,982.43 | 0 / 0 | 37.18% / 23.93% |
| EURUSD | 30 | EUR-1,099.98 / EUR-1,936.14 | EUR1,206.59 / EUR1,968.62 | 0 / 0 | 38.46% / 29.49% |
| EURUSD | 60 | EUR-1,142.98 / EUR-1,953.18 | EUR1,218.62 / EUR2,018.96 | 1 / 1 | 41.85% / 32.16% |
| GBPUSD | 15 | EUR-825.83 / EUR-1,661.69 | EUR975.09 / EUR1,742.85 | 0 / 0 | 41.15% / 33.19% |
| GBPUSD | 30 | EUR-848.51 / EUR-1,682.70 | EUR1,096.53 / EUR1,825.20 | 2 / 0 | 39.82% / 34.51% |
| GBPUSD | 60 | EUR-1,260.27 / EUR-2,020.85 | EUR1,571.58 / EUR2,215.77 | 2 / 2 | 42.40% / 37.33% |
| NZDUSD | 15 | EUR-856.05 / EUR-1,570.87 | EUR862.71 / EUR1,573.23 | 0 / 0 | 34.20% / 20.73% |
| NZDUSD | 30 | EUR-1,079.42 / EUR-1,773.43 | EUR1,082.05 / EUR1,773.87 | 0 / 0 | 38.34% / 24.35% |
| NZDUSD | 60 | EUR-1,273.59 / EUR-1,939.41 | EUR1,284.14 / EUR1,945.40 | 0 / 0 | 39.27% / 32.46% |
| USDCHF | 15 | EUR-1,523.77 / EUR-2,174.45 | EUR1,538.73 / EUR2,181.61 | 0 / 0 | 29.17% / 20.37% |
| USDCHF | 30 | EUR-1,454.51 / EUR-2,112.51 | EUR1,461.41 / EUR2,117.34 | 0 / 0 | 31.94% / 26.85% |
| USDCHF | 60 | EUR-1,431.28 / EUR-2,081.47 | EUR1,453.35 / EUR2,096.31 | 0 / 0 | 42.25% / 34.27% |

## Earlier and later stressed accounts

Earlier: 2025-09-01 to 2026-03-01 exclusive. Later: 2026-03-02 to 2026-11-11 exclusive. Each starts independently at EUR10,000; these values cannot be summed to reconstruct full-period compounding. Duration selection used earlier stressed net only, requiring trading participation and no financing/overnight violation; ties lower drawdown then name. It was locked before later/full results.

| Pair | Minutes | Earlier stressed net | Later stressed net | Selected earlier |
|---|---:|---:|---:|---|
| EURUSD | 15 | EUR-553.49 | EUR-1,490.77 | yes |
| EURUSD | 30 | EUR-688.62 | EUR-1,339.59 | no |
| EURUSD | 60 | EUR-680.23 | EUR-1,363.77 | no |
| GBPUSD | 15 | EUR-735.49 | EUR-1,003.36 | yes |
| GBPUSD | 30 | EUR-976.62 | EUR-779.83 | no |
| GBPUSD | 60 | EUR-973.84 | EUR-1,162.09 | no |
| NZDUSD | 15 | EUR-830.72 | EUR-807.78 | yes |
| NZDUSD | 30 | EUR-900.74 | EUR-960.41 | no |
| NZDUSD | 60 | EUR-1,017.69 | EUR-1,026.35 | no |
| USDCHF | 15 | EUR-952.83 | EUR-1,352.64 | yes |
| USDCHF | 30 | EUR-1,031.64 | EUR-1,205.62 | no |
| USDCHF | 60 | EUR-1,094.65 | EUR-1,105.17 | no |

## Normal-cost decomposition of selected models

Gross price P&L is an accounting proxy before modeled costs, not an attainable zero-cost return.

| Pair | Gross price P&L | Spread | Commission | Slippage | Net |
|---|---:|---:|---:|---:|---:|
| EURUSD | EUR-49.98 | EUR133.21 | EUR624.82 | EUR321.85 | EUR-1,129.86 |
| GBPUSD | EUR209.37 | EUR100.31 | EUR617.05 | EUR317.84 | EUR-825.83 |
| NZDUSD | EUR29.58 | EUR97.51 | EUR520.24 | EUR267.88 | EUR-856.05 |
| USDCHF | EUR-213.42 | EUR548.89 | EUR470.47 | EUR290.99 | EUR-1,523.77 |

## Fixed execution and costs

Both sides enter on weekdays 05:00 inclusive to 18:00 exclusive UTC, intersecting original strategy sessions. Exit after elapsed 15/30/60 wall-clock minutes or 19:00 UTC same day, whichever comes first. Missing quotes never create invented earlier fills; the first available actual M1 opening quote is used. Existing SL/TP already triggered at that opening quote takes priority over a timed market exit; daily protection retains priority.

Risk-based size remains 0.75%, max lot 0.5, aggregate exposure cap 0.75%, EUR150 daily trigger and one-position rule. Initial SL20 pips, TP2R, trailing activation1.5R/gap1R with target removal, spread cap0.9 pips and original cooldown/filters are unchanged. No tightened stop is widened, no grid/averaging/martingale, and no pair-specific tuning was performed.

Normal: observed historical spread, 1-pip missing-spread fallback, EUR3.50 commission/lot/side and 0.2-pip adverse market/stop slippage. Stress: EUR7, 0.4 pip, doubled negative financing debits and unchanged positive credits; missing-spread fallback becomes 2 pips. **Observed historical spreads are not doubled.** Take-profit limit exits have no exit slippage. Financing remained EUR0 in every account.

Spread is the bid/ask difference; slippage is the difference between expected and actual execution price; swap is financing across rollover. In live trading, changing quotes and actual fills can differ from historical bar proxies. Stress is sensitivity analysis, not a prediction that live fees will be exactly double. These commission/slippage values are declared assumptions rather than a verified broker invoice. See [MT5 execution](https://www.metatrader5.com/en/terminal/help/trading/performing_deals) and [swap specifications](https://www.mql5.com/en/book/automation/symbols/symbols_swaps).

## Data and financing audit

The available exported FX universe is EURUSD, GBPUSD, NZDUSD and USDCHF; this is not every instrument offered by MT5. BTCUSDT is excluded. EURUSD/GBPUSD/USDCHF have longer exports, but original NZDUSD M1 data starts 2025-07-28. A read-only extension attempt returned only 98,879 recent M1 bars beginning 2026-08-06. That shorter download was archived separately and not substituted for the longer existing NZDUSD.json source. The common September2025 start gives equal horizons and individually verified warm-up. Plan.json records input names, per-pair EUR valuations and history hashes.

The financing snapshot was captured from an already-running connected EUR MT5 session with Algo Trading disabled; no account ID, credentials or balance was saved. All four instruments have nonzero swap rates in the snapshot. Invalid MT5 triple-day code7 required the explicit prior Wednesday-triple assumption. Current rates are held constant across history, not reconstructed historical daily financing.

All48 complete entry/exit paths have zero financing under both GMT+3 and an independent GMT+2 interval audit, zero overnight positions and zero late exits. The policy uses UTC deadlines, so absent financing under both schedules the alternate clock is path-equivalent. Any financed/overnight trade would be retained and disqualified, never silently set to zero or deleted.

Each symbol uses its own positive EUR tick valuation/volume rules from historical exports. Valuation is constant, not a historical conversion series. Prices and some strategy dates were examined previously; earlier-only nomination does not create an untouched holdout. Three durations and one daylight window were fixed before outcomes. Pair rankings are descriptive. Historical margin, liquidity, latency, tick paths and changing minimum-stop constraints are not reconstructed.

## Validation and reproduction

**368 passed, one existing expected failure.** Twenty-one new cases cover intraday boundaries, weekends, elapsed deadlines, correct symbol history switching, nonambiguous broker symbols, rejection of no-trade/financed nominations, native SL/TP priority at gap opens, both directions/all durations, retained financing violations and real quote-gap exits. All trading tests use synthetic bars and forbid broker/order methods. Independent audit reconciles all48 account/cost ledgers and target-band counts.

```powershell
python -m src.tools.research_fx_scalping --history-root history/mt5_20261111 --snapshot reports/fx_intraday_scalping/swap_snapshot.json --output reports/fx_intraday_scalping --workers 6
```

The frozen plan records code/history hashes. Use a new output directory after a source/protocol change. Every research process forbids broker initialization/trading. No live settings changed, no bot was started and no order was placed.
