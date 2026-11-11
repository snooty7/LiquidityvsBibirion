# USDCHF EUR20k: continuous loss-reduction comparison

All accounts below start with EUR20,000 and run continuously, with **no monthly resets**. Risk is 0.5% per entry. Figures include modeled spread, commission and slippage; **swap/financing is excluded**.

## One account through the full history

15 November 2024 to 11 November 2026 exclusive. This includes the bad and better periods in one account.

| Model | Start EUR | End EUR | Net EUR | Maximum M1-close equity drawdown EUR | Mean winner EUR | EUR100-200 winners | Trades |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 20000.00 | 18815.07 | -1184.93 | 3378.89 | 107.60 | 35 | 300 |
| known_spread_0_9 | 20000.00 | 20704.85 | 704.85 | 1144.37 | 120.66 | 21 | 157 |

## Earlier bad period: 15 Nov 2024 to 15 Nov 2025 exclusive

Each row is a separate continuous account, starting at EUR20,000 at the beginning of this period.

| Model | End EUR | Net EUR | Maximum M1-close equity drawdown EUR | Mean winner EUR | EUR100-200 winners | Trades |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 17730.67 | -2269.33 | 3007.49 | 105.04 | 18 | 159 |
| atr_trailing | 12789.81 | -7210.19 | 7555.09 | 79.43 | 10 | 208 |
| atr_fixed2r | 12890.04 | -7109.96 | 7816.73 | 158.77 | 43 | 196 |
| unrestricted_entries | 16291.39 | -3708.61 | 4618.09 | 93.69 | 15 | 202 |
| known_spread_0_9 | 19505.74 | -494.26 | 703.79 | 105.83 | 1 | 18 |

## Later period: 16 Nov 2025 to 11 Nov 2026 exclusive

Each row is a separate continuous account, starting at EUR20,000 at the beginning of this period.

| Model | End EUR | Net EUR | Maximum M1-close equity drawdown EUR | Mean winner EUR | EUR100-200 winners | Trades |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 21221.05 | 1221.05 | 921.81 | 124.25 | 20 | 141 |
| atr_trailing | 15983.48 | -4016.52 | 4369.54 | 95.78 | 10 | 191 |
| atr_fixed2r | 17546.27 | -2453.73 | 2898.40 | 173.03 | 59 | 184 |
| unrestricted_entries | 20325.05 | 325.05 | 1687.34 | 122.23 | 25 | 167 |
| known_spread_0_9 | 21208.93 | 1208.93 | 927.61 | 124.83 | 20 | 139 |

## Doubled commission/slippage

| Model | Earlier stressed net EUR | Later stressed net EUR |
|---|---:|---:|
| baseline | -3059.50 | 410.91 |
| atr_trailing | -8191.71 | -4571.68 |
| atr_fixed2r | -8032.76 | -3906.31 |
| unrestricted_entries | -4601.58 | -565.56 |
| known_spread_0_9 | -579.41 | 418.38 |

| Full-history account | Stressed end EUR | Stressed net EUR | Stressed M1-close equity drawdown EUR |
|---|---:|---:|---:|
| baseline | 17296.80 | -2703.20 | 3981.51 |
| known_spread_0_9 | 19864.38 | -135.62 | 1291.36 |

## Rules and interpretation

- `baseline`: Original M30/M1 model, 20-pip initial SL and original R trailing
- `atr_trailing`: Initial stop =1.5*mean true range of last 14 CLOSED M30 bars; original 2R TP and 1R trailing. Risk-derived size, broker max volume rather than inherited lot ceiling.
- `atr_fixed2r`: Same ATR-scaled initial stop; fixed 2R target, no trailing. Existing position-risk loss guard retained.
- `unrestricted_entries`: Original fixed stop/trailing; remove inherited session, spread and EUR150 daily-loss entry restrictions in PAPER ONLY. Spread and all other modeled execution costs still charged. Single-position and 0.5% exposure guard retained.
- `known_spread_0_9`: original reference with spread <=0.9 pip. This threshold and its earlier favorable comparisons were already known; it is a control, not a new discovery. No parameter search was performed for this addendum.
- The original earlier-period nomination remains `baseline`. The known-cost addendum does not rerank or alter it. All candidates remain visible; no sample-count gate hides results.
- Full accounts carry cash, positions and guard state through the entire history, including the calendar gap between the two separately reported periods.
- Equity drawdown is the fall from a previous account-equity peak, including floating P&L at observed M1 closes, incurred entry fees and actual simulated exits. Intrabar/tick losses can be greater. Drawdown is already part of the path; it is not subtracted from net profit again.
- Mean winner is calculated only over positive-net trades. Count in EUR100-200 is disclosed separately; not every winner reaches that band.
- Base costs: historical spread, EUR3.50/lot/side assumed commission, 0.2-pip adverse market/stop slippage. Stress doubles commission/slippage to EUR7.00/0.4 pip, leaves observed spread unchanged, and doubles missing-spread fallback from 1 to 2 pips.
- EUR20,000 start; 0.5% risk per entry, risk-derived lots, one position and 0.5% concurrent exposure cap. Never widen an already-open stop, average down or increase size after a loss. All changes are paper-only.
- Earlier and later dates and baseline outcomes were previously examined; this is exploratory historical validation, not untouched forward evidence.
- A larger mean winner does not guarantee every successful trade reaches EUR100-200; trade counts and target-band counts are retained.
- Swap/financing excluded; commission/slippage assumptions and constant historical symbol valuation. No full tick/latency model.
- Broker volume maximum is honored; historical margin requirements and broker minimum stop-distance constraints are not reconstructed.
- M1-close equity drawdown can be smaller than intrabar drawdown. Daily guard is a trigger, not a guaranteed loss bound.
- The unrestricted paper scenario disables the daily guard and can incur larger daily losses; it does not alter the live protection. Research hooks are not enabled in live profiles.
- No tuning of the four hypotheses after outcomes. Both years were previously examined; no statistical confirmation is claimed.
- No live configuration changed, no broker connection during replay, no bot started and no orders placed.

## Reproduce

```powershell
python -m src.tools.research_loss_reduction --workers 4
python -m src.tools.complete_loss_reduction --workers 4
```

The original protocol is plan.json; original older-data choice is locked_selection.json. cost_benchmark/plan.json registers the separate known-reference completion. report.json retains all actual simulated trades and both original and addendum results.
