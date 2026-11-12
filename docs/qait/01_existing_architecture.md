# Existing architecture assessment

Assessment date: 2026-11-12 (Europe/Sofia). Scope: source inspection and offline regression tests; no terminal connection, order submission, live process startup, or production configuration changes.

## Repository baseline

Remote: https://github.com/snooty7/LiquidityvsBibirion. `git fetch origin` completed. Remote HEAD is `main`; local and remote `main` were at `8d04e3d`. The clean working checkout was `feature/cost-aware-walk-forward`, at `eb6f50b`, matching its remote and containing 27 commits beyond `origin/main`, with no commits unique to main. Those commits add risk regressions, offline history/cost infrastructure, shared filters, and research workflows relevant to this task.

Created the requested `feature/qait-adaptive-strategy` from `eb6f50b` to retain that work. This is a stacked branch: a future PR targeting main will include the inherited commits until its base branch is merged. Prefer reviewing against `feature/cost-aware-walk-forward` meanwhile; do not silently reset to main or duplicate the risk work. No merge or push was performed during this assessment.

## Configuration first

Reviewed `src/services/config.py`, `config/settings.example.json`, selected non-secret operational fields in `config/settings.json`, and configuration consumers. Defaults merge with the requested JSON file, then an optional sibling `*.local.json`; symbol lists replace rather than merge. Runtime and symbol settings become frozen dataclasses. There is no standalone RiskManager class: pure sizing lives in `src/risk/sizing.py`, while entry and position guards live in the orchestrator.

Important distinctions:

- Python defaults have `dry_run=true`, but both checked-in `settings.example.json` and `settings.json` specify `dry_run=false`. Do not start the bot to inspect it or assume the example is safe for development.
- The inspected settings file specifies daily realized-loss limit 150, fixed-loss fallback 30, `per_trade_loss_guard_mode=position_risk`, `per_trade_loss_risk_multiple=1.0`, four maximum positions, 0.50% maximum open risk, and R-multiple trailing. Monetary values are treated as account currency by valuation even where configuration/log labels say USD; verify account denomination before interpreting them.
- Its six profiles are EURUSD 92001/M5, EURUSD 92008/M30, EURUSD 92014/M1, USDCHF 92024/M30, EURUSD 92025/M5, and NZDUSD 92028/M5. Omitted strategy modes resolve to `liquidity_sweep`; 92014 uses `trend_micro_burst_v2`, and 92025/92028 use `volume_sweep_reclaim`.
- Other profiles live under `live/` and separate research configuration files. The active terminal/process configuration was not queried; the inspected file is not proof of deployment state. Production credentials and local overrides were not altered.

## Modules and flow

| Boundary | Source and responsibility | Reuse / limitation |
|---|---|---|
| Configuration | `src/services/config.py`: defaults, dataclasses, loading, validation | Extend with an optional disabled adaptive section; preserve legacy resolution |
| Signals | `src/strategy/liquidity.py`, `htf_models.py` | Deterministic price/volume setup detection; retain existing public behavior |
| Confirmation | `src/strategy/confirmations.py` | C3/C4, CISD, sweep/displacement/MSS, displacement-only helper, session scalp confirmation |
| Filters | `src/strategy/filters.py` | Spread, EMA bias, local order blocks, optional normalized EMA-slope filter |
| Risk | `src/risk/sizing.py` | Risk sizing, monetary exposure, protection direction, daily loss predicate |
| Orchestration | `src/engine/orchestrator.py` | Profile dispatch, pending setup lifecycle, final gates, sizing, positions, execution and persistence |
| Broker | `src/execution/mt5_adapter.py` | MT5 initialization, rates/ticks, metadata, orders, close/modify, deal history |
| Recovery | `src/persistence/` | SQLite pending setups, execution state, events, initial risk baselines, retry/recovery |
| Offline replay | `src/tools/backtest_mt5.py`, `src/backtesting/` | Shared strategy imports, validated history, cost-aware bar simulation |
| Research | `src/tools/walk_forward.py`, `research_*.py`, `render_*.py` | Chronological folds, frozen studies, cost stress, reports and audits |
| Dashboard | `dashboard/server.py`, `data.py`, `app.js`, `export_static.py` | Existing local snapshot API and static export; no new framework needed |

`run()` restores state, applies daily protection and manages positions; `process_symbol()` gets rates and processes each newly completed entry bar once. It dispatches strategy detection, creates or refreshes a persistent pending setup, waits for configured confirmation and expires stale setups. Semantic signal keys and persisted state help prevent duplicate execution/replay after restart.

Before submission, the entry path checks session, optional news blackout, cooldown, spread, existing branch position, higher-timeframe bias/optional long filter, valid protection, and optional order-block proximity. It sizes from the resolved stop and risk percentage, measures proposed monetary risk, and applies position/exposure caps unless the existing `ignore_portfolio_cap` flag bypasses them. Dry run records a signal and returns before the order call. Successful submission is reconciled to a broker position and initial stop distance is persisted. This flow must remain authoritative for any future adaptive signal.

Validated strategy modes include liquidity sweeps; session-open scalp; opening-range breakout v2; H4-bias micro burst; trend micro burst v2; trend-day acceleration; BTC multi-timeframe trend/retest/reclaim; volume sweep/reclaim; and H1/H4 trend-pullback and range-retest models. Additional detector functions in research are not necessarily dispatchable live modes. Config validation accepts `sweep_displacement_only`, but `process_symbol()` currently excludes it in its entry validation: resolve and test that mismatch before offering it as an adaptive option.

## Liquidity and structure inventory

| Feature | Existing implementation | Qualification |
|---|---|---|
| Liquidity levels/sweeps | `extract_pivot_levels`, `detect_sweep_signal`, `evaluate_sweep_significance` | Swing high/low levels; penetration and close-back behavior; significance checks |
| Anti-chop/context | `evaluate_range_filter`, compression and overlap helpers | Useful observations, not a five-class regime detector |
| BOS/MSS | `evaluate_sweep_displacement_mss_confirmation` | Directional displacement candle closes through recent extrema; no general event taxonomy distinguishing continuation BOS from reversal MSS |
| Trend structure | `_collect_swings`, `_structure_state`, BTC trend/retest logic | Private helpers; make explicit shared interfaces only with parity checks |
| Order blocks | `find_local_order_block`, distance and override helpers | Opposing candle plus subsequent impulse, age, body/wick zone and distance constraints |
| FVG | `_find_zone` in `src/tools/research_htf_liquidity_sweep_bos_fvg.py` | Three-candle price-gap heuristic with order-block fallback; isolated research logic, not shared live FVG lifecycle tracking |
| Liquidity targets | `_nearest_level` and BTC model target/protection output; prior-day/equal levels in research | Partial reuse; not a general target map shared by all strategies |
| Premium/discount | No dedicated shared implementation found | Requires an explicit causal dealing-range definition |
| Indicators/volume | `_atr_series`, `_adx_value`, EMA, volume ratios | Existing deterministic helpers, not ML or exchange order-flow data |

Many existing functions expect a forming-bar sentinel and use `rates[-2]` or `rates[:-1]`; others, including H1/H4 models, require closed-only input. The replay appends a dummy forming bar where needed and uses `_available_closed_bars` to enforce `open_time + duration <= decision_time`. Preserve these distinct contracts through adapters. Pivots require right-side confirmation: make a pivot available only after its confirmation bars have closed, never at its pivot timestamp. Audit level extraction for dependence on a supplied forming candle before reusing it for causal adaptive features.

MT5's timeframe map includes D1, H4, H1, M30, M15, M5 and M1. `src/backtesting/history.py` currently excludes D1. Its UTC M1 aggregation requires complete buckets and discards gaps; adding D1 requires a declared calendar/session policy, not just adding a dictionary entry.

## MT5 / QuoMarkets

The adapter uses the installed `MetaTrader5` package and `mt5.initialize()` against the local terminal session. No QuoMarkets-specific adapter or explicit QuoMarkets integration was found in the inspected source/configuration references. If that broker is used, it is mediated by the terminal login; actual broker server, account mode, leverage, contract specifications and permissions remain unverified. No claim of broker certification or live compatibility testing is made.

Execution supports fill-mode fallback, price-protected market entry, close reconciliation including partial fills, and SL/TP modification. Partial-fill handling during a full close is not a strategy for scheduled partial profit taking. Broker deviations are expressed in points. The adapter does not establish a general pre-entry margin/freeze/minimum-stop validation contract; trailing management reads `trade_stops_level`, but broker rejection is not a substitute for deterministic preflight. Fresh-quote age and realized slippage limits need explicit review.

## Risk and exit semantics to preserve

- `calc_lot_by_risk` computes equity times risk percentage divided by stop distance and pip value, caps volume and rounds down to broker step with Decimal. It rejects unaffordable minimum lots, invalid inputs and missing valuation instead of raising exposure to the minimum.
- `calc_position_risk_money` returns infinite risk for missing stops or unavailable valuation. Portfolio guards combine existing and proposed risk and reject unknown exposure. Their scope is configured symbols/magics, not all account positions; correlation and currency concentration are not modeled. `one_position_per_symbol` is checked with a magic filter and therefore acts per branch.
- Daily loss uses configured bot magics' realized deals and cost accounting; unknown broker history blocks entries without falsely latching the daily-loss flag. Nonpositive limits disable the guard. Live dry-run daily protection is bypassed, so dry run alone does not prove live guard behavior.
- `resolve_loss_guard` uses initial position risk times `per_trade_loss_risk_multiple` in `position_risk` mode, falling back to the configured fixed monetary cap when a usable risk threshold cannot be computed. At 1.0 this is one initial risk unit, not a new universal fixed 30-unit entry-risk cap. Do not reinterpret `max_loss_per_trade_usd` as an additional sizing cap in this mode.
- Entry SL/TP normally use configured pips and RR; model setup context can override structural stops, targets and risk. Size only after resolving final protection. Explicitly reject adaptive overrides that increase the authorized risk budget.
- Persisted initial risk distances support stable R-based exits after trailing. Trailing can move to break-even and then tighten; it does not loosen an existing stop. Time exits and adverse-close/body exits exist. General ATR/structure/liquidity exit selection and scheduled partial exits need shared, independently tested policies.

## Backtesting, tests and dashboard

`HistoricalData` validates bid OHLC, ordered unique UTC timestamps, spread and broker volume/valuation metadata; it fingerprints supplied source bars independently of derived caches. JSON history loading is offline. Explicit MT5 history download is a separate capability and was not invoked.

`ExecutionCosts` models historical spread in points (or a declared fixed/fallback spread), commission per lot per side and adverse slippage. Replay shares signal/confirmation/filter imports and several risk/exit helpers with live orchestration, but their control flows remain separate and require parity tests. It cannot reconstruct tick paths, historical valuation changes, swap, financing, latency or broker margin/minimum-stop histories.

`walk_forward.py` provides rolling chronological train/embargo/test folds and training-only branch selection, holding cash when none qualifies. Metrics include trades, win rate, profit factor, net/gross P&L, component costs, mean R and realized-cash-flow drawdown. Generic walk-forward branches/folds are independently funded/reset; summing them is not a compounded multi-symbol portfolio. Later study scripts contain continuous-account experiments, which should be assessed and reused explicitly rather than conflated with generic evaluator behavior. General Sharpe, drawdown from marked equity, uncertainty intervals, regime/session breakdowns and concurrent correlated-portfolio evaluation need extensions.

Dashboard snapshots combine MT5 candles and CSV stages/levels for M1/M5/M15/M30, with recent signal cards. The server initializes MT5, so it was inspected rather than started. Reuse its snapshot contract and static exporter for optional adaptive observations; leave all existing keys and display behavior intact.

Offline baseline command:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_sizing.py tests/test_risk_regressions.py tests/test_liquidity.py tests/test_confirmations.py tests/test_filters.py tests/test_walk_forward.py tests/test_dashboard_data.py tests/test_dashboard_server.py
```

Observed: **101 passed, 1 xfailed in 1.15s**. The expected failure is `test_extract_pivot_levels_returns_latest_first`, already marked for an expectation mismatch in pivot ordering; it remains an explicit prerequisite for promoting pivot behavior into shared adaptive features. This is a selected regression baseline, not the full suite, a profitability result, or broker validation. No new engine has been implemented. See [research](02_qait_research.md) and the [proposed architecture and implementation plan](03_adaptive_architecture.md).
