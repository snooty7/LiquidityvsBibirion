# USDCHF spread <=0.9: cost-resilience improvement

**Earlier-stress nominee: `trail_later_1_5`. Meets declared descriptive objective: True.**

EUR20,000 starting capital, 0.5% risk per entry. One continuous account per scenario, no monthly resets. Full period: 15 November 2024 through 10 November 2026 UTC. **Swap/financing is excluded.**

## Full account: normal and doubled costs

| Model | Normal end EUR | Normal net EUR | Doubled-cost end EUR | Doubled-cost net EUR | Stressed equity DD EUR | Stressed mean winner EUR | EUR100-200 winners | Trades |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| trail_later_1_5 | 21671.15 | 1671.15 | 20744.46 | 744.46 | 1118.54 | 156.54 | 23 | 145 |
| fresh_confirmation | 21053.60 | 1053.60 | 20194.04 | 194.04 | 1291.71 | 127.41 | 16 | 152 |
| baseline | 20704.85 | 704.85 | 19864.38 | -135.62 | 1291.36 | 118.04 | 17 | 157 |
| trail_gap_1_25 | 20211.12 | 211.12 | 19393.08 | -606.92 | 1486.36 | 123.17 | 13 | 151 |
| stronger_confirmation | 20049.98 | 49.98 | 19288.22 | -711.78 | 1472.93 | 113.78 | 14 | 149 |

## Separate continuous periods under doubled costs

Each period starts with EUR20,000 independently. These balances are not added into a single account. The earlier period alone chooses the fixed nominee; full-history rankings above are descriptive.

| Model | Earlier net EUR | Earlier equity DD EUR | Later net EUR | Later equity DD EUR | Later mean winner EUR |
|---|---:|---:|---:|---:|---:|
| trail_later_1_5 | -177.15 | 597.55 | 922.17 | 1128.68 | 156.77 |
| fresh_confirmation | -689.89 | 888.95 | 865.75 | 1086.32 | 131.92 |
| baseline | -579.41 | 778.47 | 418.38 | 1174.96 | 121.07 |
| trail_gap_1_25 | -721.81 | 870.14 | 96.22 | 1568.25 | 128.06 |
| stronger_confirmation | -778.81 | 973.97 | 38.11 | 1033.31 | 119.30 |

## Winning trades versus all trades: full doubled-cost account

| Model | Mean winner EUR | Mean loser EUR | Mean all EUR | Largest loss EUR | Winners | EUR100-200 winners | Winners above EUR200 |
|---|---:|---:|---:|---:|---:|---:|---:|
| trail_later_1_5 | 156.54 | -107.97 | 5.13 | -142.37 | 62 | 23 | 16 |
| fresh_confirmation | 127.41 | -98.15 | 1.28 | -142.37 | 67 | 16 | 16 |
| baseline | 118.04 | -96.53 | -0.86 | -139.27 | 70 | 17 | 15 |
| trail_gap_1_25 | 123.17 | -87.88 | -4.02 | -136.18 | 60 | 13 | 13 |
| stronger_confirmation | 113.78 | -96.51 | -4.78 | -111.21 | 65 | 14 | 14 |

## Fixed hypotheses and accounting

- `baseline`: Original 1R activation / 1R trailing gap and M1 confirmation
- `trail_later_1_5`: Activate trailing at 1.5R; original 1R gap
- `trail_gap_1_25`: Original 1R activation, trailing gap 1.25R; existing SL can only improve
- `stronger_confirmation`: Displacement range multiple 2.0 instead of 1.8
- `fresh_confirmation`: Setup expiry 3 M30 bars instead of 5
- EUR20,000 starting balance, 0.5% risk per entry, 0.5 max lot, 20-pip initial SL and 2R initial TP; spread cap 0.9; original daily/portfolio guards, sessions, cooldown and single-position rule. No martingale/averaging or widening existing stops.
- Nominate highest net in earlier-year doubled-cost replay only; tie lower M1-close equity drawdown, then name. Lock before later or full-history replays. Report every hypothesis including rejected nominees; no parameter amendment after outcomes.
- Each window is a separate continuous EUR20k account, no monthly resets. Full window carries equity/positions across both years. Drawdown includes open P&L at observed M1 closes and incurred entry commission, with actual simulated fills on exits.
- Success criterion: Nominee full-history base AND doubled-cost net positive, mean net winner EUR100-200 and at least one winning trade in that band in each scenario; later doubled-cost net also positive with mean winner EUR100-200. Counts and all other outcomes disclosed. Descriptive historical criterion, not live approval.
- Normal costs are historical spread, EUR3.50/lot/side commission and 0.2-pip adverse market/stop slippage.
- These dates were examined repeatedly in prior research. This is exploratory improvement on reused history; positivity does not prove future profitability.
- Only earlier-year stress selects the fixed nominee. The full-history comparison includes selection data and is descriptive, not an untouched holdout.
- Historical spreads, assumed commissions/slippage and constant symbol valuation. Swap/overnight financing, latency, historical margin/minimum-stop constraints and full tick paths are not modeled.
- Doubled costs means EUR7.00/lot/side commission and 0.4-pip adverse market/stop slippage instead of EUR3.50/0.2 pip. Observed spread is unchanged; missing-spread fallback doubles from 1 to 2 pips.
- M1-close drawdown can be smaller than intrabar drawdown. Daily loss guard is a trigger, not a guaranteed loss bound.
- Mean winning trade excludes losses; net for all trades, count in target band and mean losing trade are disclosed. No promise that every successful trade earns EUR100-200.
- No active settings changed. Broker initialization and order methods are blocked during offline replay. No bot started or real orders placed.

## Reproduce and audit

```powershell
python -m src.tools.research_spread_resilience --workers 4
python -m src.tools.render_spread_resilience reports/usdchf_spread_resilience/report.json
```

plan.json records frozen hypotheses, settings and code/data hashes; locked_selection.json records the older-stress choice before later/full outcomes. report.json retains all 30 replays and actual simulated trades. audit.json independently reconstructs their account paths and cost/goal metrics.
