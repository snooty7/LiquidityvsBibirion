# Signal alignment repair and validation

Date: 2026-11-12. The signal/timeframe defects are repaired. **The frozen scoring/full-adaptive arms still take no historical trades. No threshold was lowered and no performance improvement is claimed.** Everything remains disabled by default, with no adaptive live order route or live trades.

## Defects and corrections

1. The adapter omitted M1 although profile 92001 confirms M5 sweeps on M1. It now loads completed confirmation candles from the existing branch configuration and reuses its displacement/recent-extrema confirmation rules. Only bars starting after the M5 sweep closes may confirm it. Break strength uses that confirmation timeframe's causal ATR; the adaptive displacement floor remains in force.
2. The adapter discarded the pending sweep and rediscovered another event using different pivots/history. It now carries the exact branch, side, level and sweep candle in a typed anchor. It verifies source pivot availability, sweep geometry/significance, expiry and one-shot liquidity consumption. It never substitutes another recent sweep. High/low provenance is explicit because the existing baseline map combines both kinds.
3. Longer source-level history initially expanded the feature gap policy to unrelated older data. Feature/regime/zone windows remain fixed at their original settings. Extended provenance validates OHLC/order throughout and continuity in the actual pivot-to-sweep, sweep ATR and confirmation ATR intervals. A hole in a required interval blocks; an unrelated old hole cannot erase current features.

The contracts and first diagnostic correction are recorded in [the investigation](07_signal_alignment_investigation.md). Controlled tests establish a valid M5 sweep/M1 break with **no second M5 break**, plus real policy/protection/sizing integration. Tests also reject future/pre-close confirmations, stale/incorrect anchors, consumed liquidity, required-history gaps, mixed decision-time provenance, duplicate proposals, abnormal spreads and unaffordable lots. A synthetic source-high BUY case verifies the baseline's untyped pivot-map semantics without removing the consumed-level gate.

## Fixed experiment

No change to .65 score threshold; .30/.25/.20/.15/.10 weights; regime/MTF requirements; one-shot consumption; missing order-flow handling; risk percentages/caps; stop buffer/RR; costs; equity; instruments or chronological windows. `src/risk`, live execution/orchestration, service configuration, adaptive numeric configuration, `config/` and `live/` have no changes relative to `1f4afdc`.

New protocols were frozen before replay. Their adaptive values, effective original configuration hash, history hash, costs, equity and folds compare equal to the original protocols. The old results were not overwritten. The intermediate `alignment_92001` reports are diagnostic artifacts with the expanded-provenance defect; the **final evidence** is `aligned_92001`.

- [Final base protocol](../../reports/qait/aligned_92001/protocol.json) and [report](../../reports/qait/aligned_92001/base/report.json).
- [Final doubled-cost protocol](../../reports/qait/aligned_92001/stress_protocol.json) and [report](../../reports/qait/aligned_92001/doubled_costs/report.json).
- [Alignment/control audit](../../reports/qait/aligned_92001/alignment_audit.json), [independent arithmetic audit](../../reports/qait/aligned_92001/audit.json), and [repeat evidence](../../reports/qait/aligned_92001/reproducibility.json).

## Why no trades remain

The final base run has 63 full-adaptive candidate observations over train/validation/test phases. Counts overlap and include repeated observations in rolling windows:

| Evidence or rejection | Observations |
|---|---:|
| Exact, verified sweeps | 3 (2 distinct anchors) |
| Verified post-close M1 confirmations | 2 (1 distinct anchor) |
| Already-consumed source liquidity | 51 |
| Expired anchor | 7 |
| Required pivot history gapped | 1 |
| Anchor bar unavailable due to current M5 gap | 1 |
| Verified sweep without later confirmation | 1 |
| Below unchanged score threshold | 63 |
| Uncertain regime | 30 |
| High-volatility regime | 22 |
| Higher-timeframe conflict | 37 |

The baseline can revisit old levels; the adaptive engine's pre-existing one-shot liquidity requirement rejects those revisits. That intentional eligibility difference remains. The two M1 confirmation observations describe the same anchor in overlapping folds; they are not independent confirmations or trades. Its score is .2330, its regime is uncertain, and its higher-timeframe direction conflicts. Correctly recognizing its M1 break therefore does not make it eligible.

The corrected source diagnostics replace vague missing-sweep/missing-structure explanations with exact anchor rejection reasons. They do not justify weakening freshness, consumption, risk, missing-flow or regime gates. No independent delayed-entry stream was introduced, so this remains an intersection with the existing strategy's candidate timing.

Both base and doubled-cost test phases still show zero scoring/full-adaptive/shadow positions. All **24 baseline/regime control ledgers** are identical to the original study. Baseline test results remain 10/+16.97 and 7/+5.46 under base costs; regime-only remains 0/0 and 3/-1.20. Doubled-cost controls are likewise unchanged. These are independent reset-fold development results, not a continuous portfolio or untouched holdout.

## Verification

- Full Python suite: **368 passed, 1 pre-existing expected failure**.
- Dashboard JavaScript syntax and dependency-free DOM contract pass.
- Alignment audit verifies exact sweep identities, actual confirmation timeframe/causality, fixed score arithmetic, unavailable order flow, frozen input equality and 24 unchanged control ledgers.
- Independent stdlib arithmetic audit passes 92 trade rows across 60 ledgers, including costs, fill-based P&L, equity and broker volumes.
- Full-adaptive/shadow serialized ledgers remain identical. Existing controlled non-empty shadow and new real-policy alignment tests avoid relying solely on empty historical ledgers.
- Repeat base replay is byte-identical to the final base report. Audit scripts are `tools/audit_qait_alignment.py` and `tools/audit_qait_results.py`.

Replay command (use a fresh output directory):

```powershell
.venv/Scripts/python.exe -m src.tools.research_adaptive run --protocol reports/qait/aligned_92001/protocol.json --output NEW_OUTPUT_DIRECTORY
```

The old data's development status and all earlier [deployment limitations](06_deployment_guide.md) remain. Live activation, a new candidate stream, relaxed signal eligibility and parameter calibration are outside this repair.
