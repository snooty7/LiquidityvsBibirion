# Observed adaptive research results

Date: 2026-11-12. **No adaptive performance improvement is established. No live trades were placed.** The initial fixed scoring/full-adaptive settings held cash throughout both test windows. This is an observed no-trade outcome, not evidence that the strategy is profitable or ready for activation.

Follow-up: [signal/timeframe alignment repair and validation](08_signal_alignment_results.md). The original artifacts below remain immutable; corrected protocols and diagnostics are linked in the follow-up.

## Scope and artifacts

Implemented the broker-independent regime/MTF/structure/scoring/proposal engine, shared risk preflight, configurable pure exits and offline partial-fill accounting, ML observer/split contracts, frozen five-arm runner, metrics and optional dashboard observations. Defaults remain disabled. Existing strategy dispatch, production settings, credentials and MT5 order code were preserved.

Initial comparison: saved EURUSD history, existing profile 92001, October 2026, two rolling development folds. Training lasts seven days, validation three days, each separation has a one-day embargo, and each test lasts seven days. Starting equity is 10,000 account-currency units per phase/fold. This is previously researched development history, not an untouched out-of-sample release test.

- [Base protocol](../../reports/qait/eurusd_92001/protocol.json) and [full base report](../../reports/qait/eurusd_92001/base/report.json).
- [Doubled-cost protocol](../../reports/qait/eurusd_92001/stress_protocol.json) and [full sensitivity report](../../reports/qait/eurusd_92001/doubled_costs/report.json).
- [Independent arithmetic audit](../../reports/qait/eurusd_92001/audit.json); its stdlib source is `tools/audit_qait_results.py`.

The reports preserve training/validation results, trade ledgers, all observations, rejections, component/raw evidence, costs, data/code/config hashes, per-regime/instrument/session metrics and shadow status. Parameters were not adjusted after these results.

## Development test windows

Values below are net after modeled costs, in saved-metadata account currency. Each cell is **positions / net P&L**. These are independent reset-fold results, not continuous portfolio returns.

| Arm | Oct 13–20 base | Oct 20–27 base | Oct 13–20 doubled costs | Oct 20–27 doubled costs |
|---|---:|---:|---:|---:|
| Existing baseline | 10 / +16.97 | 7 / +5.46 | 10 / +53.59 | 7 / -12.68 |
| Baseline + regime gate | 0 / 0.00 | 3 / -1.20 | 0 / 0.00 | 3 / -4.56 |
| Baseline + score gate | 0 / 0.00 | 0 / 0.00 | 0 / 0.00 | 0 / 0.00 |
| Full adaptive | 0 / 0.00 | 0 / 0.00 | 0 / 0.00 | 0 / 0.00 |
| Full adaptive + ML shadow | 0 / 0.00 | 0 / 0.00 | 0 / 0.00 | 0 / 0.00 |

Base baseline fold 1: win rate 50.00%, profit factor 1.380, mean net R .1846, maximum realized drawdown 29.64. Fold 2: win rate 57.14%, profit factor 1.270, mean net R .0849, maximum realized drawdown 13.83. The regime gate reduced participation and lost money in its three-trade test sample. None of these small samples supports a claim of improved risk-adjusted performance.

Doubled costs are a complete replay, not subtraction from fixed trades. Spread changes can change bid/ask stop touches and trailing exit trajectories. In fold 1, one short trade's trailing-stop result changed from +.92 to +48.61, which explains why this particular sensitivity run has higher net P&L despite higher costs. That path-dependent outcome is retained, not treated as a general cost benefit. Fold 2 deteriorated under doubled costs. Both reports expose fill prices and reasons for inspection.

Realized-calendar-daily Sharpe is available in the JSON with its 365-day annualization explicitly labeled. Seven-day test windows make it unstable and unfit for model selection. Marked-equity drawdown is unavailable. Win rate, profit factor, mean R and Sharpe are null for no-trade arms. Confidence intervals are unavailable because these windows fail the declared 30-day/20-position minimum. Sample sizes remain visible.

## No-trade diagnosis

Across the base study's train/validation/test phases, the full-adaptive policy recorded 63 baseline candidate observations. Rejections can overlap:

| Reason | Candidate occurrences |
|---|---:|
| Score below frozen .65 threshold | 63 |
| No qualifying post-sweep structure event | 53 |
| Conflicting higher-timeframe direction | 37 |
| Uncertain regime | 30 |
| High-volatility regime | 22 |
| No matching recent sweep | 46 |
| Gapped M5 context | 2 |

The baseline's entry/confirmation timing and the adaptive engine's separate same-entry-timeframe sweep/structure definition are strict intersections. The current adapter can reject a baseline confirmation that lacks its required post-sweep M5 break. It does not wait independently for a later adaptive trigger. This is an integration/design constraint to study, not a reason to relabel missing structure as confirmation or weaken risk guards. A genuinely separate adaptive candidate stream would require another registered implementation/study.

Order flow is unavailable and never replaced by tick-volume confirmation. LightGBM/XGBoost are absent, no model was fitted, and shadow observations explicitly report `model_unavailable`. All six phase comparisons in each cost study had identical adaptive/shadow trade ledgers; because these historical ledgers are empty, a separate controlled integration test verifies identity with a non-empty ledger as well. No predictive ML improvement was measured.

## Verification and release status

The full Python regression suite reports **353 passed, 1 pre-existing xfailed**. JavaScript syntax and a dependency-free DOM contract pass, covering hidden defaults, observation fields, safe text rendering and reset to legacy snapshots. The independent audit passed **92 trade rows across 60 phase/arm ledgers**. The base study was rerun against the same frozen inputs and its serialized report was byte-identical; see [repeat evidence](../../reports/qait/eurusd_92001/reproducibility.json). The pre-existing pivot-ordering xfail remains visible; the adaptive structure implementation uses its own explicit confirmation-time contract rather than changing legacy ordering semantics.

Review corrected repeated use of swept liquidity, OB lifecycle state and invalid-input checks before the published protocols were frozen. Earlier development outputs are retained locally under `.git/qait-initial-review`; the published report uses the corrected code and newly frozen hashes. No score, regime, risk or cost threshold was tuned in response to the economic results.

The independent audit recomputes money from entry/exit fill prices, tick valuation, volume and commission without importing the trading implementation; it checks cost totals, equity reconciliation, broker volume constraints and full shadow-ledger identity. It is an arithmetic check, not an audit of historical tick realism or profitability.

**Promotion remains blocked by evidence and missing capabilities:** no genuine holdout, insufficient active-trade samples, no fitted/calibrated ML, no marked-equity series, no synchronized multi-symbol continuous-account comparison, no adaptive live execution adapter or persisted live partial milestones, and incomplete historical broker metadata/financing/tick realism. Account-wide exposure and correlation controls exist as tested pure preflight services but were not exercised against a real account. This release is suitable for further offline research and code review only; it is not an assertion that every proposed production capability is complete.
