# Consumed-liquidity lifecycle correction: results

Date: 2026-11-12. **The anchored consumed-liquidity rule falsely rejected active baseline levels. It is corrected without changing numerical thresholds or risk controls. No test-window performance improvement is established. Everything remains disabled, with no live trades.**

## Audited contract

The baseline rebuilds a newest-first high/low pivot map from its rolling rates and keeps `max_levels` entries. It does not permanently delete a level when price crosses it. Duplicate execution is controlled separately by remembered side/level signal keys, pending state, cooldown, positions and recovery.

The adaptive verifier incorrectly treated any intervening low below a BUY level or high above a SELL level as permanent consumption. This also confused ordinary time on one side of an untyped source pivot with level retirement. The [pre-replay audit](09_level_lifecycle_audit.md) specifies the correction.

Anchored eligibility now reconstructs the source map at the sweep's creation time using the unchanged `extract_pivot_levels` and `detect_sweep_signal`. It requires both active membership and the detector's actual first-priority side/level. It still verifies confirmed-before-sweep provenance, complete required windows, buffered sweep geometry/significance, expiry, post-close confirmation and every subsequent score/MTF/regime/risk check. It records the source lifecycle, pivot kind and number of prior crossings explicitly.

Source history includes the confirmation delay so that the original rolling window can be reconstructed exactly. Later map turnover does not retroactively cancel an already-valid pending anchor. Missing history, actual rank/window retirement, wrong priority or stale/duplicate setups still reject. Standalone adaptive structure/target definitions are unchanged; the correction is specific to baseline-anchored eligibility.

## Frozen validation

New protocols use the same EURUSD 92001 settings, saved history, 7/3/7-day train/validation/test windows, embargo, equity, base/doubled costs, .65 score threshold, weights, regime/MTF settings and risk budgets as the preceding study. Old artifacts remain immutable.

- [Base protocol](../../reports/qait/lifecycle_92001/protocol.json) and [full report](../../reports/qait/lifecycle_92001/base/report.json).
- [Doubled-cost protocol](../../reports/qait/lifecycle_92001/stress_protocol.json) and [full report](../../reports/qait/lifecycle_92001/doubled_costs/report.json).
- [Independent source-lifecycle audit](../../reports/qait/lifecycle_92001/lifecycle_audit.json), [control/alignment audit](../../reports/qait/lifecycle_92001/alignment_audit.json), [arithmetic audit](../../reports/qait/lifecycle_92001/audit.json), and [repeat evidence](../../reports/qait/lifecycle_92001/reproducibility.json).

For the full-adaptive arm across all train/validation/test observations, both cost scenarios show:

| Diagnostic | Before | Corrected |
|---|---:|---:|
| Candidate observations | 63 | 63 |
| Source sweeps verified | 3 | 54 |
| Post-close confirmations verified | 2 | 31 |
| False consumed-level rejections | 51 | 0 |
| Score-eligible observations | 0 | 2 |

The restored 51 observations represent 41 distinct source anchors; rolling windows repeat some observations. They are **not 51 additional trades**. The independent auditor reconstructed every accepted source map directly from raw saved candles, preserving pivot ordering, duplicate prices, source window, forming sentinel and rank cap. All 51 restored observations were previously crossed levels still active under that exact baseline map.

## Trade outcomes and remaining gates

| Phase/arm | Base costs | Doubled costs |
|---|---:|---:|
| Fold 1 training, scoring-only | 2 positions / +14.91 | 2 positions / +12.43 |
| Other training/validation scoring-only phases | 0 | 0 |
| Both test windows, scoring-only | 0 | 0 |
| Every phase, full adaptive and ML shadow | 0 | 0 |

The two scoring-eligible full-arm training observations score .6704 and .7721. Full-adaptive hard gates still reject them for high volatility and conflicting higher-timeframe direction respectively. The scoring-only comparison intentionally tests the score gate separately; it retains the existing baseline sizing/execution guards and does not represent full adaptive eligibility. No gate was weakened to create trades.

Other full-arm rejections include 61 below-threshold observations, 23 without post-close confirmation, seven expired anchors and required-data gaps. Counts overlap. The same 30 uncertain-regime, 22 high-volatility and 37 timeframe-conflict observations remain. All **24 baseline/regime control ledgers** are identical to the preceding study, and full-adaptive/ML-shadow ledgers remain identical.

These short, previously researched development windows do not establish profitability. The two new scoring-only positions occur in training, not test; no OOS improvement is claimed and no parameter was selected from these returns.

## Verification and boundaries

- **373 Python tests passed; one pre-existing expected failure.** JavaScript syntax and dashboard DOM checks pass.
- Controlled tests cover active repeated crossings, BUY/SELL symmetry, rank and history retirement, source priority, sufficient creation-time history, later map turnover, exact pending identity, duplicate execution and unchanged sizing/spread rejection.
- Independent audits reconcile **96 trade rows across 60 ledgers** and verify source-map provenance, causal confirmation, frozen input equality and unchanged control ledgers.
- The repeated base report is byte-identical to the published base report.
- `src/risk`, MT5 execution, live orchestration, service/numeric adaptive configuration and production profiles are unchanged. No live process was started or strategy activated.

Replay with a fresh output directory:

```powershell
.venv/Scripts/python.exe -m src.tools.research_adaptive run --protocol reports/qait/lifecycle_92001/protocol.json --output NEW_OUTPUT_DIRECTORY
```

The [research-only deployment boundaries](06_deployment_guide.md) remain. A new candidate stream, independent model/parameter calibration, live activation and broader portfolio validation are not part of this repair.
