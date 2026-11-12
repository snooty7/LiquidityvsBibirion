# Scoring and feature normalization: results

Date: 2026-11-12. **Feature-contract bugs are fixed, with no weight/threshold tuning or weaker risk controls. One additional scoring-only training position appears per cost scenario. Test-window positions and full-adaptive positions remain zero. Everything remains disabled; no live trades were placed.**

## Findings and repairs

The [decision record](13_scoring_normalization_audit.md) specifies these changes before replay:

1. **Interval proximity:** distance to a zone midpoint penalized entries inside or near a wide zone. Proximity now uses the existing order-block interval-distance helper: zero inside, otherwise distance to the nearest edge. The original `max(0, 1-distance/(2*ATR))` scale and maximum aggregation across active same-side FVG/OB zones are retained. No width weight or additive FVG/OB bonus was introduced.
2. **Consistent ATR units:** regime ATR and sweep/confirmation normalization used different seed conventions after the previous regime repair. Adaptive components now share the corrected actual-transition ATR implementation at the existing period and causal fixed window. Legacy strategy indicators are unchanged. Sweep and confirmation ratios remain on their respective timeframes and observation times; the displacement floor remains mandatory.
3. **Regime compatibility:** an opposing trend could receive positive compatibility evidence. Trend bonus now requires agreement with the candidate; ranging remains compatible with either side. Unknown/extreme regimes provide zero evidence, and missing/invalid regime inputs are unavailable. Existing hard regime/MTF checks remain authoritative.
4. **Invalid normalization:** `min(1.0, NaN)` could hide an invalid event strength as full evidence. Invalid/future events, inconsistent raw ratios, invalid ATR and malformed zones now produce explicit unavailable observations. Required missing evidence blocks; optional missing evidence remains zero under a fixed denominator.

Raw move, ATR, interval bounds, actual entry price, distance and scale are recorded so each contribution can be reconstructed independently. Aggregation by component name, the original boundary tolerance, genuine zero values and missing order-flow handling were already correct and are preserved. Missing flow is never renormalized away or replaced by tick volume; it still caps otherwise perfect evidence at .90.

## Frozen comparison

The .65 threshold, .30/.25/.20/.15/.10 weights, 2-ATR distance scale, clipping bounds, required features, numeric gate settings, RR, risk budgets, original settings/data hashes, costs, equity and chronological windows match the preceding gate protocols. Old artifacts are immutable. New evidence:

- [Base protocol](../../reports/qait/scoring_92001/protocol.json) and [report](../../reports/qait/scoring_92001/base/report.json).
- [Doubled-cost protocol](../../reports/qait/scoring_92001/stress_protocol.json) and [report](../../reports/qait/scoring_92001/doubled_costs/report.json).
- [Independent scoring audit](../../reports/qait/scoring_92001/scoring_audit.json), [gate audit](../../reports/qait/scoring_92001/gate_audit.json), [arithmetic audit](../../reports/qait/scoring_92001/audit.json) and [repeat evidence](../../reports/qait/scoring_92001/reproducibility.json).

| Scoring-only phase | Base costs | Doubled costs |
|---|---:|---:|
| Fold 1 training | 2 positions / +14.91 | 2 positions / +12.43 |
| Fold 2 training | 1 position / +6.51 | 1 position / +5.27 |
| Both validation phases | 0 | 0 |
| Both test windows | 0 | 0 |

Full adaptive and ML shadow remain at zero positions in every phase. Baseline and regime-only ledgers remain identical across all **24 control comparisons**. Of all 60 phase/arm ledgers, only fold-2 training scoring-only changes in each cost scenario. Fold results are independent reset accounts, not a combined portfolio return.

Across the 63 full-adaptive observations, 38 sweep values and 20 break values change from consistent ATR seeding, 51 zone values change from interval geometry, and one missing regime input changes from zero to unavailable. The direction-compatibility correction is also covered by controlled opposing-trend tests. Counts describe observations, not additional trades.

Three training observations meet the unchanged score threshold:

| Candidate epoch | Previous score | Corrected score | Full-adaptive rejection retained |
|---|---:|---:|---|
| 1790878200 | .6704 | .6748 | HIGH_VOLATILITY |
| 1791275400 | .7721 | .7855 | H1 direction conflict |
| 1791439500 | .6316 | .6854 | UNCERTAIN regime |

The third case demonstrates a corrected scoring rejection, not permission to bypass its hard regime gate. The remaining 60 full-arm observations stay below threshold or lack required evidence. The scoring-only arm is an experimental isolated gate comparison; it is not full adaptive eligibility or live activation.

## Independent verification

- **433 Python tests passed; one pre-existing expected failure.** Dashboard syntax/DOM checks pass.
- Controlled tests cover wide-zone/edge geometry, BUY/SELL symmetry, scaling/translation invariance, maximum aggregation, ratio clipping, invalid/future data, compatible/opposed regimes, missing versus genuine zero, all component permutations, threshold boundaries and the missing-flow ceiling. Existing duplicate, sizing and spread tests remain intact.
- `tools/audit_qait_scoring.py` imports no strategy implementation. It derives fill prices from native candles/spread/slippage, recomputes event-time ATRs from raw candles, verifies raw moves and interval distances, side compatibility and every fixed-weight contribution. Per cost scenario it verifies **100 baseline/full-arm scores**, 88 sweep ratios, 51 structure ratios and 92 zone normalizations. These overlapping evaluations are not independent trades or new market samples.
- Gate verification still finds 22 valid ATR-extreme observations and 37 genuine timeframe oppositions, with all 104 unique native HTF/M1 close boundaries matching.
- Independent arithmetic audit reconciles **98 trade rows across 60 ledgers**. Full-adaptive/ML-shadow identity remains intact.
- Repeated base replay is byte-identical. Risk code, live execution/orchestration, production profiles, numerical adaptive settings and legacy indicator helpers are unchanged.

These short, previously researched development windows establish no OOS or risk-adjusted performance improvement. See the [consolidated main-goal status](15_main_goal_status.md) for what this engineering work does and does not establish.
