# Proposed adaptive architecture and implementation plan

Status: **DESIGN ONLY — awaiting user approval before implementation.** This document fulfills the post-research proposal, not Phase 3 completion. Phases 4–6 results and deployment documents will be written when those activities actually occur. All names below are proposed interfaces/paths, not existing features.

## Decision boundary and data contracts

Use a deterministic adaptive evaluator that returns a proposal plus auditable rejection reasons. It has no MT5 client and cannot submit, modify or close trades. Existing strategies retain their dispatch and configuration. A future opt-in adaptive branch uses the existing execution/risk path after its own signal evaluation; passing a score never bypasses a guard.

Flow: completed market snapshot -> regime and timeframe context -> liquidity/structure observations -> score/eligibility -> entry and exit proposal -> authoritative risk checks -> existing execution adapter. A separate ML observer sees the same frozen feature vector and writes shadow output only.

Proposed immutable dataclasses:

- `MarketSnapshot`: symbol, decision time, per-timeframe closed candles, source timestamps, quote/spread observations and quality flags. Every candle must satisfy close time <= decision time. Validate ordering, gaps, OHLC, finite values, warm-up and maximum age. Declare broker-to-UTC conversion and daily/session boundaries.
- `FeatureObservation`: name, normalized value in [0,1] or unavailable, availability reason, observation time and raw evidence/parameters. Never replace missing data with confirmation.
- `RegimeResult`, `TimeframeContext`, `StructureEvent`, `ScoreBreakdown`, `EntryProposal`, `ExitDecision`, `ShadowPrediction`: include version, effective configuration hash, source-data identity, reason codes and causal timestamps. Structure events carry pivot and confirmation times separately.
- Stable proposal key: strategy version, symbol, branch, side and triggering closed-bar/event identity. Reuse persistent semantic-key checks to prevent duplicates and stale restart execution.

## Modules and reuse

| Proposed path / change | Responsibility | Existing reuse |
|---|---|---|
| `src/strategy/adaptive/models.py` | Immutable contracts and reason codes | Existing signal/result dataclass conventions |
| `src/strategy/adaptive/context.py` | Closed-time joins, freshness and MTF agreement | `_available_closed_bars`, HTF closed-context checks; explicit adapters for sentinel-based legacy detectors |
| `src/strategy/adaptive/regime.py` | Five-class deterministic regime evaluation | Extract/wrap ATR, ADX, EMA and swing helpers with parity tests |
| `src/strategy/adaptive/structure.py` | Timestamped sweeps/BOS/MSS/FVG/OB/targets/zones | Sweep/confirmation/OB functions; audited research `_find_zone` as a starting definition |
| `src/strategy/adaptive/scoring.py` | Validated weights and feature availability | New pure logic; no broker dependency |
| `src/strategy/adaptive/engine.py` | Regime eligibility, scoring and entry proposals | Existing strategy primitives and protection context |
| `src/strategy/adaptive/exits.py` | Pure entry-protection and subsequent exit decisions | Existing R-trailing and time/adverse-exit helpers |
| `src/strategy/adaptive/ml_shadow.py` | Optional observer/model metadata and unavailable handling | No mandatory ML runtime dependency |
| `src/risk/` shared preflight service | Validate proposal risk, broker limits and exposure | Existing sizing, projected exposure and daily protection; orchestrator remains authoritative |
| `src/services/config.py` | Optional adaptive configuration, strict validation | Existing defaults/dataclass behavior retained |
| `src/backtesting/history.py`, replay hooks | D1/calendar policy and shared evaluator/exit invocation | Validated history, fingerprints, costs and existing replay |
| `src/tools/research_adaptive.py` | Frozen five-arm chronological study/report | Walk-forward folds, existing audit/report patterns |
| Existing dashboard files | Optional adaptive snapshot fields and overlays | Current server, static exporter, charts and cards |

Do not split or rewrite the entire orchestrator as part of this work. Extract only helpers required for shared risk/signal behavior, with regression evidence. Dynamic leverage and hedging stay false; initially reject configuration enabling either because their execution/margin semantics are outside the first implementation.

## Regime and multi-timeframe definitions

Support configurable D1/H4/H1/M15/M5/M1 roles, with a frozen required subset per profile. D1 offline support must include native/broker-session boundaries or an explicitly documented UTC research calendar. FX daily candles cannot be assumed to contain every M1 minute. Do not fill closed-session gaps with invented candles.

Regimes are `TRENDING_BULLISH`, `TRENDING_BEARISH`, `RANGING`, `HIGH_VOLATILITY`, `UNCERTAIN`. Proposed precedence: invalid/stale/insufficient context -> UNCERTAIN; extreme ATR percentile or realized-volatility threshold -> HIGH_VOLATILITY; ADX plus aligned EMA slope, confirmed structure and momentum -> directional trend; low ADX with bounded structure/overlap -> RANGING; disagreement -> UNCERTAIN. Thresholds, lookbacks and hysteresis are frozen experimental settings. Rolling ATR percentiles and realized log-return volatility use only observations available at the decision; never fit full-history thresholds. Explicitly test the existing indicator smoothing definitions before calling them standard Wilder indicators.

A higher-timeframe trend is context, never permission to skip a lower-timeframe sweep/confirmation. MTF conflicts, required-data absence and UNCERTAIN/extreme volatility block new entries by default. A regime eligibility matrix selects only predeclared eligible setup families; it cannot choose an untested branch from recent test returns.

## Structure and score definitions

Formalize BOS as a close beyond a previously confirmed swing in the prevailing structure direction, and MSS as the first qualified opposite break after a sweep/context change. Retain the legacy confirmation definition for baseline branches. FVG is a three-closed-candle non-overlap, available only on the third close; track formation, mitigation, expiry and invalidation causally. Order-block selection retains impulse/age/distance evidence. Premium/discount uses a declared, already-confirmed dealing range; liquidity targets must exist at the decision time.

Initial experimental weights: sweep .30, structure .25, FVG/OB .20, regime .15, order flow .10. Validate finite nonnegative weights summing to 1 and a threshold in [0,1]. Component mappings must expose raw penetration/ATR, break strength, gap/zone quality, regime compatibility and actual flow evidence with declared clipping thresholds. Avoid double-counting FVG and OB: use a predeclared combined quality rule, not additive duplicates.

Default missing-feature policy: preserve the fixed denominator; unavailable optional components contribute zero evidence and appear as unavailable in the breakdown. Thus missing flow caps the score at .90, rather than silently renormalizing or treating it as true. Require sweep, structure and regime availability plus independent hard gates; configurations marking flow required must reject missing flow. Tick-volume activity may be displayed as its own proxy but cannot fill the order-flow confirmation slot. Thresholds are selected in training/validation, frozen before OOS and never claimed optimal in advance. The score is evidence aggregation, not a calibrated probability.

## Risk first and controlled exits

Before adding strategy complexity, validate the existing boundaries and extend missing checks without altering legacy mode semantics:

1. Preserve `position_risk` and multiple 1.0, initial-risk persistence, daily-loss/history failure behavior and downward volume rounding. Do not reinterpret the fixed-loss fallback as a new entry sizing rule.
2. Resolve structural/ATR stop and liquidity target first; reject zero/wrong-side/too-near protection and insufficient net RR. Size against that exact stop within the configured branch risk budget, lot cap and broker minimum/step.
3. Validate quote age, spread, price rounding/tick size, broker minimum-stop/freeze restrictions and any available margin preflight through the isolated adapter. Limit deviation and recheck after quote refresh; log actual slippage/fill reconciliation. No silent SL widening to satisfy the broker.
4. Apply maximum position count and projected portfolio risk. Adaptive configurations cannot use `ignore_portfolio_cap`. Snapshot positions once, deduplicate tickets and declare whether the policy includes external positions; do not claim existing configured-magic caps cover the entire account.
5. Add conservative currency/directional concentration limits and a past-data-only correlation gate with declared lookback, aligned return timestamps, minimum observations and missing-data rejection. Estimate correlated exposure without adding offsetting hedge trades or raising risk for diversification/ML confidence.

Initial protection may use an adverse confirmed structure level with a declared ATR buffer; selecting that stop before entry is distinct from loosening an existing stop. Liquidity targets must meet configured RR after modeled costs. Subsequent SL decisions may keep or tighten only. Preserve the original R denominator. Break-even, R/ATR trailing, time exits and optional partial exits are individually configurable and off unless explicitly enabled in research. Partial exits require broker-step-valid close volume and residual volume, one-shot persistent milestones, restart reconciliation and cost-aware replay. Initially deliver them as offline-tested decisions before any broker integration.

## Optional ML evaluation

Compare LightGBM and XGBoost only in a separate optional offline experiment; neither is a required dependency or assumed superior. Evaluate installation footprint, reproducibility, training time, calibration, Brier/log loss, regime stability and incremental predictive information over the deterministic baseline. Select neither if data or evidence is insufficient.

Use regime, ATR/ADX, causal sweep/structure/FVG features, momentum, declared volume proxy, spread, cyclical time of day and MTF agreement. Define a fixed outcome horizon/label with costs and a recorded label-availability timestamp. Purge overlapping outcome windows across train/validation/OOS boundaries, embargo as required, fit preprocessing/calibration on training/validation only and freeze all artifacts. Record model/data/code hashes and random seeds. An unavailable or incompatible model yields explicit `model_unavailable`, never a guessed probability. Shadow output must have no influence on eligibility, size, leverage or exits; arm 5 must produce exactly the same orders and fills as arm 4.

## Reproducible validation and dashboard plan

Compare the same frozen original branch under (1) unchanged baseline, (2) regime gate, (3) score gate, (4) full deterministic adaptive entries/exits, (5) identical arm 4 with ML shadow. Use the same symbol universe, date windows, starting capital, costs and history hashes; identify changed stop/exit behavior explicitly for arm 4. Keep all rejected candidates and parameter searches in the audit trail.

Use chronological training, separate validation and untouched OOS; extend existing train/embargo/test infrastructure rather than treating training fit as validation. Perform walk-forward selection using only earlier data. Previously researched history is development data, not a fresh untouched holdout. Report both independent per-instrument results and a genuinely synchronized continuous-account portfolio with shared daily/exposure caps; do not add independent returns and call them portfolio performance.

Measure trade count, win rate, profit factor, daily-return Sharpe with declared annualization/calendar, marked-equity and realized drawdown separately, mean net R, monetary expectancy, net profit, loss streaks, and regime/instrument/session breakdowns. Define initial R and assign regime/session at entry. Use historical spreads plus stated missing-spread fallback, per-side commission, adverse slippage and cost stress. Disclose swap/valuation/margin/tick-path limitations. Report sample sizes, block-bootstrap confidence intervals where defensible, and unavailable metrics honestly for small/zero-trade samples. No improvement claim until supported by OOS evidence and risk-guard validation.

Add an optional `adaptive` snapshot object carrying regime, MTF directions, liquidity and BOS/MSS events, FVG/OB zones, normalized score contributions/availability, proposed entry/SL/TP, proposed monetary/percentage risk, ML shadow probability/status, rejection reasons and comparison summaries. Keep current keys, static export and legacy charts functional. Mark proposal/shadow data clearly and timestamp it; the dashboard does not activate strategies or submit trades.

## Ordered delivery and acceptance gates after approval

1. **Risk and contract foundation:** freeze baseline/config expectations; verify sizing, guard semantics, metadata/protection validation and completed-bar adapters. Acceptance: missing/invalid/stale data fails closed; broker constraints and duplicate/restart cases covered without real MT5 calls.
2. **Shared observations:** implement D1 policy, regime/MTF and audited structure/FVG helpers with legacy parity checks. Acceptance: appending future/forming bars cannot change past observations; conflicts/extreme volatility yield declared no-trade outcomes.
3. **Scoring and deterministic proposals:** add validated disabled configuration and pure evaluator. Acceptance: normalized auditable scores, explicit unavailable flow, valid stops/RR, no risk increase and no execution path enabled by default.
4. **Shared exits and offline comparison:** integrate pure decisions into replay and run frozen five-arm protocol, initially without an ML model. Acceptance: costs reconcile, guard parity holds, sample sizes/limitations are reported; full regression suite passes.
5. **ML shadow and dashboard:** evaluate optional libraries only if the dataset permits, add observer and backward-compatible display. Acceptance: missing model is harmless and explicit; ML on/off leaves trade ledger identical; old snapshots still render.
6. **Documentation and review:** complete `04_backtesting_methodology.md`, `05_results.md`, `06_deployment_guide.md` with actual commands/results and remaining risks. Complete source/test review, focused commits, push requested feature branch and prepare PR as authorized by the task after implementation is complete. No merge or automatic activation. Offline acceptance does not authorize live trades.

Required tests span missing/gapped data, incomplete candles, stale signals/quotes, abnormal spreads, MTF conflicts, volatility extremes, invalid stop distances, broker min/max/step restrictions, duplicate proposals and restarts, unavailable model/flow, no-trade conditions, daily-loss boundaries and correlation/exposure failures. Use fake adapters that prohibit initialization/order calls; keep real history downloads an explicit separate operation. Run full regressions before the eventual push, plus reproducibility reruns of the approved study. Do not use new tests that merely mirror implementation arithmetic.

Approval requested: the above risk-first, disabled-by-default implementation scope. Research access limitations remain documented; approval would authorize independent engine development, not claim that QAIT internals were verified.
