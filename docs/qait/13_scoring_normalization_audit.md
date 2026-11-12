# Scoring/normalization audit: decision before replay

Date: 2026-11-12. This is a feature-contract audit, not a parameter search. No trade count or profit outcome is required for acceptance. Weights, .65 threshold, clipping bounds, 2-ATR proximity scale, required features, missing-flow policy, all hard gates, risk controls and frozen experiment inputs remain unchanged.

Findings from source semantics before new historical replay:

1. Zone proximity uses distance to the midpoint, while `order_block_distance_pips` defines distance to the zone interval (zero inside). A wide active zone can receive zero proximity evidence for an inside entry. Correct the geometric distance using the existing interval-distance helper; retain `max` aggregation over active same-side FVG/OB zones, clipping and the existing 2-ATR scale. Do not introduce additive double counting or a zone-width weight.
2. Adaptive regime ATR was corrected to actual-transition initialization, but sweep/confirmation normalization still uses the legacy first-transition seed. Share the corrected closed-window ATR implementation across adaptive components only, preserving periods, windows, event-time causality and the displacement floor. Do not change legacy strategy indicators.
3. The component described as regime compatibility currently awards 1 for any recognized trend, including one opposing the candidate. Opposite trends must receive zero, not positive evidence. Ranging remains compatible with either side; unknown/extreme regimes remain zero. Missing/invalid input must be unavailable, not a successful observation. Hard regime/MTF rejection stays authoritative.
4. `min(1.0, strength)` can mask NaN as 1.0 before the scorer validates it. Invalid strength/ATR/zone inputs must yield explicit unavailable observations. Missing optional evidence continues to contribute zero under a fixed denominator; required missing evidence blocks.

Add raw move/ATR and zone interval/distance/scale provenance so normalization can be independently reproduced. Aggregation already maps by feature name, keeps weights fixed, and excludes missing flow from confirmation; preserve those properties and the existing boundary tolerance.

Controlled tests will cover BUY/SELL symmetry, interval boundaries and wide zones, maximum aggregation, raw ratio clipping, scale/translation invariance, invalid/future inputs, regime direction compatibility, missing versus genuine zero values, permutations, exact score contributions and threshold boundaries. They must retain duplicate, data-quality, risk sizing and spread rejection. Then freeze the same base/stress comparison under `reports/qait/scoring_92001`, preserving prior artifacts. No historical threshold or feature scaling will be tuned after replay.
