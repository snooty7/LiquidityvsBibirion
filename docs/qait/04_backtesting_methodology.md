# Adaptive backtesting methodology

Implementation date: 2026-11-12. This release provides reproducible **offline research**, not production adaptive execution.

## Shared code and the five comparisons

`src/tools/research_adaptive.py` freezes a protocol before running and uses the existing `run_backtest` engine with explicit saved `HistoricalData`. Providing a research entry/exit policy without offline history raises an error before MT5 initialization. The trading orchestrator's dispatch, credentials and settings files are unchanged.

The five arms are:

1. **baseline:** the original strategy and protection, with an observational callback that returns no overrides. An integration test verifies identical results/ledger with and without a no-op callback.
2. **regime:** the baseline plus an entry gate rejecting uncertain/extreme regimes and trades opposed to a directional regime.
3. **scoring:** the baseline plus the fixed-denominator score/required-feature gate. This arm does not also impose all full-adaptive hard gates.
4. **adaptive:** eligible baseline candidates pass the regime, MTF, post-sweep structure, score, liquidity-target, RR and adaptive preflight gates; protection uses structure plus an ATR buffer. Existing final sizing, daily loss and exit guards remain authoritative.
5. **adaptive_shadow:** identical to arm 4, with optional observer output. The runner compares the entire serialized trade ledgers and fails if they differ.

The full arm adapts candidates from the existing strategy; it is not an independent discovery stream or a replica of QAIT. New strategy code has no MT5 import or execution method. Existing live behavior is unaffected by an adaptive observation setting.

The [alignment repair](07_signal_alignment_investigation.md) binds liquidity-sweep candidates to their original pending identity and configured confirmation timeframe. Existing source-level provenance can use additional past history without changing fixed feature windows. The qualified lower-timeframe recent-extrema break is explicitly labeled `CONFIRMATION_BREAK`; it is not relabeled as an independent M5 swing BOS/MSS. Only a post-sweep-close confirmation is usable. Other confirmation modes without an anchored definition reject explicitly rather than treating unimplemented evidence as true.

## Frozen inputs and windows

`freeze` records code digest, original configuration-file hash, effective configuration hash (including local override effects), redacted effective settings, source-history file hash, adaptive parameters, broker valuation/volume data via the history bundle, costs, equity, and chronological fold boundaries. Code hashing normalizes newline conventions. Notification URL/token values are redacted in the public protocol; hashes still detect input changes.

`run` refuses changed source/data/effective configuration and refuses to overwrite an existing run directory. Output includes source/history/protocol hashes, all five phase ledgers, feature availability, raw observations, rejection reasons, exit observations and metrics. Results are strict JSON; unavailable ratios are null rather than Infinity/NaN. No protocol, threshold or cost is optimized after seeing test output.

For each rolling fold the training window is followed by an embargo, validation window, another embargo and nonoverlapping test window. All windows are half-open UTC intervals. The CLI's training/validation settings are implemented by subdividing the existing chronological `make_folds` contract. Each phase starts flat with the same equity. Validation is separate from training; parameters are fixed in this release, so neither phase performs a fitted search or model selection. Additional candidate searches must get new protocols and preserve failed alternatives.

The initial study is October 2026 saved EURUSD data previously used in the repository. Its test windows are chronological development tests, **not an untouched holdout**. No statement about live or future profitability follows from them. A release decision needs longer preregistered windows and genuinely unused later data.

## Causal observations

Snapshots admit only `bar_open + timeframe_duration <= decision_time`; future and forming candles are excluded before price validation. All required series need the configured fixed warmup. Nonfinite/malformed OHLC, timestamp problems, missing data, interior gaps and stale context produce explicit unavailable reasons and block adaptive proposals.

Supported labels are D1/H4/H1/M30/M15/M5/M1. D1 explicitly means UTC midnight-to-midnight research bars. M1-derived daily buckets need all 1440 minutes; incomplete days are dropped, including short FX sessions. Native broker-session daily bars cannot be silently relabeled UTC. The optional `allow_utc_weekend_gaps` policy permits only missing bar-open times on Saturday/Sunday, with gaps at most three days; it never creates candles. It is false by default and explicitly true in the frozen FX study. Holiday or weekday gaps still block context.

Pivots become observable after right-side confirmation; a candle cannot create its own swept level. BOS/MSS are event types distinct from the legacy confirmation's local-extrema definition. Swept/broken levels are removed from the active liquidity target map. FVGs are available on the third candle's close, with active/mitigated/invalidated/expired states. Local OB selection reuses the existing impulse/age helper. Dealing-range midpoint provides descriptive premium/discount context from confirmed pivots.

Regimes use existing ATR/ADX smoothing, EMA alignment, causal channel structure, normalized momentum, past ATR ranks and realized log-return volatility. This reuses the repository's indicator definitions; it does not claim numerical equivalence to every external Wilder implementation. Near-equal ATR values count as ties rather than artificial record volatility. There is no learned threshold, online learning or hysteresis model in this release.

Scores expose the .30/.25/.20/.15/.10 contributions and normalized/raw evidence. Missing order flow remains unavailable and contributes zero under a fixed denominator, capping an otherwise perfect score at .90. Required flow blocks when absent. Tick volume never substitutes for exchange flow. FVG/OB quality uses a maximum proximity contribution, avoiding additive double counting. The score is not a probability.

## Costs and risk

Replay uses bid OHLC; buys enter ask and sells exit ask. Historical spread is MT5 points converted to pips, with a declared missing-spread fallback. Commission is per lot **per side**, in account currency. Adverse slippage applies to market/stop fills; TP limits keep the existing limit-fill assumption. Stop gaps use adverse open/stop handling. The optional `spread_multiplier` defaults to 1 for all existing callers and permits stress on actual historical spreads as well as fallback quotes.

Base study assumptions: 10,000 account-currency starting equity per phase/fold, historical spread, 1-pip missing-spread fallback, commission 3.5 per lot per side, slippage .2 pips. Doubled-cost sensitivity: historical/fallback spread multiplier 2, commission 7 and slippage .4 pips. These are declared research assumptions, not verified historical QuoMarkets invoices or fills. Symbol valuation is the saved metadata; account denomination and changing historical FX conversion remain limitations.

Adaptive preflight validates risk authorization, tick alignment, stop/RR/cost constraints, quote freshness, spread, daily limit, broker min/step/max volume, unique-position exposure, maximum count, currency concentration and correlation exposure. An unknown external position valuation or correlation blocks. Absolute correlation above .7 gives no hedge credit; the correlation estimator uses aligned past returns and an explicit sample/lookback bound. Unsupported currency mappings block rather than assuming crypto is FX. Live margin availability must be explicitly verified; the research adapter declares its offline metadata assumptions.

The isolated branch replay has no simultaneous other positions. Its original daily and position-risk semantics remain in charge, including `position_risk` with multiple 1.0. The fixed-loss fallback is not reinterpreted as a new initial sizing cap. ATR/structure protection is resolved before lots are sized. Stops can only tighten afterward, using unchanged initial R. Optional break-even, trailing and partial exits default off; partial closes allocate entry/exit costs and remaining risk/volume proportionally, reconcile the residual broker step, and execute at a completed close with adverse market slippage. The simulator records a one-shot milestone after the simulated fill. Broker milestone persistence and live partial activation are not implemented.

## Metrics and uncertainty

Reports include positions, exit fills, win rate, profit factor, cost totals, net P&L, mean net R, monetary/R expectancy, realized drawdown and loss streaks. Partial fills are consolidated by original position for trade counts and mean R. Daily realized cash-flow returns include zero-trade UTC calendar days and annualize Sharpe with sqrt(365). This is labeled **realized daily Sharpe**, not marked-equity Sharpe. No-trade ratios are unavailable.

Regime, symbol and fixed UTC six-hour session breakdowns use entry metadata. Realized daily cash flows allocate commissions on entry/exit days. Marked-equity maximum drawdown is explicitly null because the baseline replay does not export a complete marked equity series. It is not replaced with realized drawdown. The 95% net-P&L interval uses 500 circular five-day block resamples, seed 1729, and is unavailable below 30 calendar days or 20 positions. The first study's short per-phase windows therefore do not support intervals.

## ML candidate evaluation

Neither LightGBM nor XGBoost is installed in this virtual environment; no dependency was added. Both are candidates for a separate chronological, purged experiment, not accepted trading filters. LightGBM's CPU deterministic settings and seed controls are documented in its [official parameters](https://lightgbm.readthedocs.io/en/stable/Parameters.html). XGBoost documents tree methods, seed/objective settings in its [official parameters](https://xgboost.readthedocs.io/en/stable/parameter.html), and Windows wheel/runtime requirements in its [installation guide](https://xgboost.readthedocs.io/en/stable/install.html). These sources establish configurable capabilities, not model superiority or profitability.

Prefer a fixed CPU build, fixed seed/thread settings, versioned feature schema and recorded environment if either is evaluated. Compare calibration/Brier/log loss, stability and training footprint after purging outcome windows crossing train/validation/test boundaries. `chronological_split` enforces label-availability timestamps and embargo separation. The observer rejects unavailable features, invalid probabilities or model errors explicitly. No model is loaded from pickle or downloaded. The current study records `model_unavailable` and makes no fitted ML performance claim.

## Remaining validation boundaries

No swaps/financing, tick paths, latency, historical margin/freeze/stop metadata or dynamic valuation is reconstructed. No synchronized multi-symbol continuous-account comparison has been implemented; independent fold/branch returns must not be added and called portfolio performance. The pure account-wide exposure service is tested, but does not establish portfolio simulation or live broker integration. These gaps, together with a genuine holdout and sufficient samples, are prerequisites for promotion beyond research. No improvement claim or automatic activation is justified by this release.
