# USDCHF SELL-flat profit hypotheses — EUR10,000, risk 0.75%

**Outcome: no tested alternative increased full-period net profit over the existing SELL-flat candidate under either cost level or clock assumption.** All three alternatives lose money under stressed costs in both fixed-clock scenarios. The current candidate remains the strongest of these four tested configurations; this does not establish future profitability.

Instrument: **USDCHF (MT5 USDCHF-)**, M30 signals with M1 confirmation. Full continuous account period: **2024-11-15 00:00 UTC to 2026-11-11 00:00 UTC exclusive**. Capital EUR10,000; risk-derived entry sizing at0.75%, initial price-risk budget EUR75. Returns are total over nearly two years, not monthly or annual.

## Primary comparison: broker clock GMT+3

| Model | Costs including swap | Net profit | Total return | Largest sampled equity drawdown | Net winners EUR100–200 / all trades | Win rate |
|---|---|---:|---:|---:|---:|---:|
| Existing SELL-flat candidate | Normal | EUR788.31 | 7.88% | EUR731.81 | 26 / 158 | 42.41% |
| Existing SELL-flat candidate | Stressed | EUR131.37 | 1.31% | EUR741.88 | 23 / 156 | 42.31% |
| Spread cap0.7 pips | Normal | EUR-164.96 | -1.65% | EUR924.01 | 7 / 83 | 42.17% |
| Spread cap0.7 pips | Stressed | EUR-596.14 | -5.96% | EUR981.07 | 6 / 83 | 39.76% |
| Displacement threshold2.0 | Normal | EUR137.35 | 1.37% | EUR637.48 | 23 / 150 | 41.33% |
| Displacement threshold2.0 | Stressed | EUR-435.53 | -4.36% | EUR775.40 | 21 / 148 | 39.86% |
| Trailing gap1.25R | Normal | EUR414.52 | 4.15% | EUR771.34 | 22 / 155 | 43.23% |
| Trailing gap1.25R | Stressed | EUR-206.97 | -2.07% | EUR826.01 | 23 / 153 | 43.14% |

Winners in the target band have EUR100–200 inclusive **net** profit after all modeled costs. Account net includes all losing trades. Drawdown includes open P&L at observed M1 closes, incurred entry fees, financing and simulated exits; intrabar losses can be greater.

## Earlier nomination and later rejection

The registered rule selected spread0.7 using **earlier-period GMT+3 stressed net only**, before the new alternatives were evaluated on later/full periods. The baseline was already known and reused. The locked ranking is recorded in [locked_selection.json](locked_selection.json). No changes were made after seeing the alternatives' later results.

| Earlier stressed ranking | Net profit | Sampled drawdown | Trades |
|---|---:|---:|---:|
| Spread cap0.7 pips | EUR41.69 | EUR282.55 | 7 |
| Existing SELL-flat candidate | EUR-234.37 | EUR557.41 | 19 |
| Trailing gap1.25R | EUR-243.93 | EUR557.41 | 19 |
| Displacement threshold2.0 | EUR-384.99 | EUR648.27 | 20 |

The nominated spread0.7 candidate improved earlier stressed net to EUR41.69, versus baseline -EUR234.37. It subsequently lost EUR628.77 in the later stressed account and EUR596.14 in the full stressed account. This failed validation is disclosed; it is not replaced by a winner chosen retrospectively from the later period.

## All periods and both clocks

Each earlier/later window is an independent continuous EUR10,000 account. Their results cannot be summed to reconstruct the compounded full-period account. Earlier: 2024-11-15 to 2025-11-15 exclusive. Later: 2025-11-16 to 2026-11-11 exclusive.

| Model | Clock | Earlier normal/stressed net | Later normal/stressed net | Full normal/stressed net | Full stressed drawdown |
|---|---|---:|---:|---:|---:|
| Existing SELL-flat candidate | GMT+3 | EUR-126.03 / EUR-234.37 | EUR935.88 / EUR388.40 | EUR788.31 / EUR131.37 | EUR741.88 |
| Existing SELL-flat candidate | GMT+2 | EUR-99.77 / EUR-210.95 | EUR1,144.40 / EUR577.76 | EUR1,017.71 / EUR351.82 | EUR740.23 |
| Spread cap0.7 pips | GMT+3 | EUR183.41 / EUR41.69 | EUR-339.14 / EUR-628.77 | EUR-164.96 / EUR-596.14 | EUR981.07 |
| Spread cap0.7 pips | GMT+2 | EUR208.80 / EUR64.29 | EUR-246.64 / EUR-523.87 | EUR-43.18 / EUR-459.20 | EUR1,023.76 |
| Displacement threshold2.0 | GMT+3 | EUR-285.46 / EUR-384.99 | EUR428.24 / EUR-59.97 | EUR137.35 / EUR-435.53 | EUR775.40 |
| Displacement threshold2.0 | GMT+2 | EUR-261.53 / EUR-357.20 | EUR721.39 / EUR214.05 | EUR432.86 / EUR-138.95 | EUR725.75 |
| Trailing gap1.25R | GMT+3 | EUR-153.83 / EUR-243.93 | EUR592.98 / EUR33.51 | EUR414.52 / EUR-206.97 | EUR826.01 |
| Trailing gap1.25R | GMT+2 | EUR-127.57 / EUR-218.11 | EUR784.08 / EUR202.48 | EUR659.37 / EUR-17.49 | EUR823.13 |

## Exactly what changed

- Spread0.7: lower entry spread cap from0.9 to0.7 pips; execution spread still charged normally.
- Stronger confirmation: displacement range threshold2.0 instead of1.8; all other signal requirements unchanged.
- Trailing gap1.25R: activation remains1.5R; configured gap increases from1R to1.25R before each simulated entry to allow more room for larger winners. The initial stop is unchanged and an already-tightened stop can never move farther away.
- No combinations, grid search, increased size, martingale, averaging or post-result parameter changes.

All variants retain EUR10,000 start, risk0.75%, max lot0.5, initial stop20 pips, initial target2R, target removal on trailing activation, EUR150 daily trigger,0.75% aggregate exposure cap and one-position rule. SELL is closed at the first available M1 opening quote at/after23:55 broker time. New SELL entries are blocked until midnight. BUY overnight handling is unchanged. Quote gaps are not filled with invented prices; any incurred financing is retained. Live execution and live settings are untouched.

## Meaning of doubled costs

This is a declared sensitivity test for worse trading costs, not a prediction of future broker fees:

| Assumption | Normal | Stress |
|---|---:|---:|
| Commission, EUR/lot/side | 3.50 | 7.00 |
| Adverse market/stop slippage, pips | 0.2 | 0.4 |
| Negative swap debits | 1x | 2x |
| Positive swap credits | unchanged | unchanged |
| Observed historical spread | observed | same observed values |
| Fallback spread when missing, pips | 1 | 2 |

For a0.30-lot position, the assumed opening plus closing commission totals EUR2.10 normally and EUR4.20 under stress. Spread and slippage are additional. Spread is the bid/ask price difference; swap is financing charged or credited for positions held across rollover. Take-profit limit exits retain no adverse exit slippage. These are the same cost assumptions as the previous study.

Financing uses the same 2026-11-12 snapshot of point rates, held constant across history: +1.41113636 BUY and -25.75364 SELL, converted with the existing constant EUR tick valuation. MT5 returned invalid triple-day code7, so the prior explicit Wednesday triple schedule remains. Both GMT+3 and GMT+2 broker-midnight assumptions are reported; historical clock/DST policy and historical daily swap changes were not reconstructed.

## Validation and provenance

**347 tests passed; one existing expected failure.** Four new cases verify isolated configuration changes, unchanged risk parameters, earlier-only ranking/tie handling and monotonic already-tightened stops under the larger configured trailing gap. Existing regression tests retain risk sizing, daily protection, stops, financing, quote-gap exits and future-price exclusion.

The source of the preceding study, excluding only this new research orchestrator, exactly matches its registered SHA-256. History, full reference configuration and risk runtime also match. Therefore all12 baseline ledgers are reused exactly from the preceding completed study, not estimated by scaling. All36 alternative replays were newly executed, for48 audited records total. Every balance, cost/financing ledger and target-band count reconciles. Zero forced cutoff fills conflict with an existing take-profit at the opening quote.

All hypotheses and the selection rule were registered before alternative outcomes; the nomination was locked before later/full alternative runs. Nonetheless these dates and prior strategy outcomes were already examined repeatedly. This is exploratory historical research, not an untouched holdout or a new guarantee of profitability. Margin requirements, historical stop constraints, latency, missing liquidity and tick extrema are not reconstructed.

```powershell
python -m src.tools.research_sell_flat_profit --history history/mt5_20261111/USDCHF_extended.json --reference reports/usdchf_10k_no_overnight/report.json --output reports/usdchf_10k_sell_flat_profit --workers 6
```

The plan includes history, source and reference-report hashes. Use a new output directory after changing source or assumptions. Broker initialization and trading methods are forbidden in research workers. No bot was started, no order was placed and no live settings were changed.
