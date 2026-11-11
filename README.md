# MT5 Liquidity Bot v2 Scaffold

This repository contains a modular hybrid v2 bot that combines:
- the working liquidity sweep flow from `I:\MetaTrader5`
- the modular architecture and risk-first contract from this migration repo

## Implemented slice (v2)
- Liquidity map from pivots and direct sweep signal detection
- Configurable confirmation before entry: `none`, `c3`, `c4`, `cisd`, `sweep_displacement_mss`
- Sweep significance gate and anti-chop range suppression before setup creation
- Bias filter (EMA context on configurable higher timeframe)
- Local order-block filter with max distance gating
- Risk-based lot sizing from equity and stop distance
- MT5 execution adapter with fill-mode fallback (`FOK -> IOC -> RETURN`)
- Runtime guards: session, spread, cooldown, one-position-per-symbol
- Daily loss guard with optional forced closing of bot positions
- Per-trade hard close guard aligned to modeled position risk (`per_trade_loss_guard_mode=position_risk`)
- Portfolio exposure caps (`max_open_positions_total`, `max_total_open_risk_pct`)
- SQLite persistence for pending setups, open positions, and runtime guard state
- Startup recovery that reconciles local state vs MT5 open positions (MT5 is source of truth)
- Dry-run mode and CSV event logging

## Project layout
- `src/strategy/liquidity.py` - pivot levels and sweep detection
- `src/strategy/confirmations.py` - C3/C4/CISD confirmation logic
- `src/strategy/filters.py` - bias and order-block filters
- `src/risk/sizing.py` - lot sizing and risk math helpers
- `src/execution/mt5_adapter.py` - MT5 bridge and order sending/closing
- `src/engine/orchestrator.py` - polling loop and orchestration
- `src/persistence/` - SQLite schema, repository, and recovery logic
- `src/tools/state_maintenance.py` - operational cleanup/retention tool
- `src/services/config.py` - config models and loader
- `config/settings.example.json` - starter configuration
- `tests/` - pure logic tests

## Quick start
1. Create env and install deps:
```bash
python -m venv .venv
.venv\Scripts\activate
pip install MetaTrader5 pytest tzdata
```
2. Create runtime config:
```bash
copy config\settings.example.json config\settings.json
```
3. Run bot:
```bash
python -m src.engine.orchestrator
```

## Safety defaults
- `dry_run` is `true` by default.
- Keep `dry_run=true` until symbol settings and broker behavior are validated.
- No martingale, no averaging down, no grid.

## Persistence Ops
- Risk sizing rounds volume down to the broker step. If the broker/branch minimum lot
  exceeds the risk budget, the entry is rejected rather than increased to the minimum.
- Missing or invalid symbol valuation blocks new entries; existing exposure is treated
  as unknown, not zero. Portfolio caps use the proposed order's actual lot and stop.
- Daily P&L includes entry and exit commissions, swap, fees, and reversal deals.
  Unavailable history blocks entries while position management continues.
- Once the daily loss guard triggers, liquidation retries continue with persisted
  backoff until positions are closed. Partial fills remain open until reconciled.
- Schema v3 stores immutable initial risk distances in `position_risk_baselines`.
  Live trailing, early exits, and position-risk loss guards use that baseline across
  stop updates and restarts. New fills capture their actual entry-to-stop distance.
  Existing positions without a baseline capture their current adverse stop distance;
  if the stop is absent or already at/beyond breakeven, the configured stop distance
  is captured once as a fallback and logged as `POSITION_RISK_BASELINE_CAPTURED`.
- Runtime checkpoints are persisted on a controlled cadence (`checkpoint_interval_sec`).
- Event retention runs on a controlled cadence (`maintenance_interval_sec`) and archives old events to JSONL before deletion.
- Relevant runtime config:
  - `checkpoint_interval_sec`
  - `maintenance_interval_sec`
  - `event_retention_days`
  - `event_retention_batch_size`
  - `event_archive_dir`
- Manual maintenance example:
```bash
python -m src.tools.state_maintenance --db-path bot_state.sqlite3 --retention-days 30 --archive-dir state_archives --vacuum
```

## Push Notifications
- Optional `ntfy`-style push publishing is supported for:
  - `TRADE_OK`
  - `TRADE_FAIL`
  - `RISK_CLOSE_OK`
  - `RISK_CLOSE_FAIL`
  - `POSITION_CLOSED_BROKER`
- Runtime config:
  - `push_notifications_enabled`
  - `push_notification_url`
  - `push_notification_token`
  - `push_notification_timeout_sec`
- Example:
```json
{
  "runtime": {
    "push_notifications_enabled": true,
    "push_notification_url": "https://ntfy.sh/your-topic",
    "push_notification_token": ""
  }
}
```

## Historical Backtest
- A lightweight MT5 history runner is available at `src/tools/backtest_mt5.py`.
- It reuses the current sweep, displacement/BOS confirmation, bias, order-block, and risk logic for bar-based historical validation.
- Entry protection, sizing, measured risk caps, initial-R trailing, and daily loss
  thresholds share the live definitions. Rejected risk entries are counted in `skipped_risk`.
- Optional `--commission-per-lot 3.5` models 3.5 account-currency units per lot per
  side, booked separately on the entry and exit trading days. The default is zero;
  historical bars do not provide actual commissions, fees, or swap. A daily loss
  triggered by entry costs blocks further entries and, when configured, closes the
  position on the next simulated M1 polling bar.
- Example:
```bash
python -m src.tools.backtest_mt5 --config config\settings.json --symbol EURUSD --start 2025-12-28 --end 2026-03-27 --initial-equity 100000 --trades-csv reports\backtest_eurusd.csv
```
- Optional side isolation:
```bash
python -m src.tools.backtest_mt5 --config config\settings.json --symbol EURUSD --side sell --start 2025-12-28 --end 2026-03-27 --initial-equity 100000
```
- The currently validated EURUSD demo candidate from the 180-day sweep is:
  - `confirm_expiry_bars = 3`
  - `range_filter_max_compression_ratio = 2.5`
  - `range_filter_min_overlap_ratio = 0.75`
  - `confirmation_displacement_body_ratio_min = 0.60`
  - `confirmation_displacement_range_multiple = 1.80`
  - keep `order_block_max_distance_pips = 8.0` as the base cutoff
  - optional strong-setup override:
    - `order_block_strong_override_max_distance_pips`
    - `order_block_strong_override_min_impulse_pips`
    - applies only to `sweep_displacement_mss` setups that already passed `range_ok`

## Cost-aware walk-forward branch comparison

`src/tools/walk_forward.py` compares frozen existing branch profiles. With no data
argument it stays offline and creates a branch inventory and an honest
`awaiting_history` report:

```powershell
python -m src.tools.walk_forward --output reports/walk_forward
```

The default inventory reads `config/*.json` (excluding examples and local overrides)
and `live/*/settings.json`, including configured BTC research branches.
Identical strategy/risk settings are deduplicated with source aliases retained;
different settings with the same magic remain separate profiles. Use `--configs`
to restrict the comparison, for example to the six active branches.

Recommended workflow: export broker history once, confirm broker costs, then run
offline. The following costs are illustrative assumptions, not verified charges:

```powershell
python -m src.tools.walk_forward --configs config/settings.json --history history/broker.json --start 2025-08-01 --end 2026-11-01 --train-days 90 --test-days 30 --embargo-days 1 --min-train-trades 20 --spread-mode historical --spread-pips 1.0 --commission-per-lot 3.5 --slippage-pips 0.2 --output reports/walk_forward
```

If no export exists, the following **explicit read-only history mode** can fetch
and save one, then evaluate it. It initializes the MT5 connection and reads
historical bars/symbol specifications; it never starts the orchestrator, sends an
order, or changes position protection. This mode is never enabled implicitly.

```powershell
python -m src.tools.walk_forward --configs config/settings.json --mt5-history --save-history history/broker.json --start 2025-08-01 --end 2026-11-01 --output reports/walk_forward
```

Output is standalone `report.html` plus strict `report.json`: per-fold train/test
results, branch fingerprints and data hashes, aggregate net P&L, spread/commission/
slippage decomposition, average R, realized drawdown, and training-only selections.
The selected branch must have positive net training return and the minimum trade
count. Otherwise it holds cash. Missing training data prevents selection; missing
test data is marked incomplete rather than reported as zero performance.

Windows use exclusive UTC end times. Each replay starts flat with equal equity;
test windows never overlap. Aggregate P&L sums independent fold results, without
compounding or simultaneous portfolio simulation. Warm-up data can precede each
window, but trades and outcomes cannot cross its boundary. Existing branches may
have been manually tuned on these dates already; this tool cannot certify that
history as genuinely untouched.

Offline JSON format (provide all M1 bars, not just the abbreviated row below):

```json
{
  "quote_basis": "bid",
  "symbols": {
    "EURUSD": {
      "symbol_info": {
        "digits": 5, "point": 0.00001,
        "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01,
        "trade_tick_value": 1.0, "trade_tick_size": 0.00001
      },
      "rates": {
        "M1": [
          {"time": 1754006400, "open": 1.14, "high": 1.1402,
           "low": 1.1399, "close": 1.1401, "spread": 10, "tick_volume": 123}
        ]
      }
    }
  }
}
```

Timestamps are unique sorted UTC bar-open epoch seconds. `spread` is MT5 points,
not pips; a missing spread uses `--spread-pips`, and a recorded zero stays zero.
Missing higher timeframes are derived from complete UTC M1 buckets only. Supplied
native broker timeframes are preserved when saving history, avoiding loss of
higher-timeframe candles when quiet minutes contain no ticks. Supply
enough prehistory for indicator warm-up. Long data gaps and corrupt bars are
reported rather than filled with invented prices.
The default maximum gap is three calendar days; `--max-gap-days` makes a different
market-closure tolerance explicit in the report. Warm-up is checked using actual
closed bars within the warm-up period rather than requiring a tick at its exact
calendar starting boundary.

Buys enter ask and exit bid; sells enter bid and exit ask. Market and stop fills
receive adverse slippage; take-profit limits do not. Stop gaps use the worse of
the stop and opening quote. Position sizing includes modeled entry slippage.
Commissions are in account currency per lot per side, booked on the respective
trading days. Cost decomposition describes the executed trades; it is not a
separate no-cost strategy replay, since costs can alter sizing and trade outcomes.

This remains an OHLC simulation: intrabar ordering, partial fills, latency, swap,
financing, historical currency conversion changes, and archived news blackouts
are not modeled. Drawdown is realized cash-flow drawdown rather than intratrade
equity drawdown. Native branch risk percentages differ and remain visible in the
report. None of these reports constitutes evidence of guaranteed profitability.

## Focused USDCHF M30 improvement study

```powershell
python -m src.tools.research_usdchf_m30 --history history/mt5_20261111/USDCHF_extended.json --train-days 365 --development-folds 6 --workers 6 --output reports/usdchf_m30_improvement
```

This tool is offline-only and actively blocks broker initialization and trading
methods. Eight frozen configurations vary exits or confirmation strictness while
keeping risk, initial stop distance and lot limits constant. It registers the
protocol before replay, locks selections from training data, and evaluates them
with historical spread, commission, slippage and a higher-cost stress scenario.
The fixed nomination uses only the first six training windows; the later six
test windows are its reserved confirmation period. Its full twelve-window
aggregate is descriptive, since development windows overlap nomination training.
The separate adaptive track selects using only each fold's preceding training.
All promotion gates must pass; otherwise the baseline is retained.

The initial 90-day sample-size diagnostic and a pre-test confirmation amendment
are retained for audit. Overlapping training windows are not independent samples,
and the market dates/baseline were examined previously. This is historical
research, not evidence of guaranteed future performance.

**Backtest fidelity correction:** confirmation now uses `cisd_timeframe` for
displacement/CISD modes and the setup timeframe for C3/C4, matching live behavior.
Earlier all-branch results that fed M1 into a configured M5 confirmation are
marked legacy and must not be used to promote those settings. The focused study
establishes a corrected baseline before comparing alternatives.

See [the focused study](reports/usdchf_m30_improvement/README.md) and
[the initial diagnostic](reports/usdchf_m30_initial_90d/README.md).
The separate `--study confirmation_alignment` mode compares the configured M5
baseline with explicit M1 confirmation and full setup-expiry context. It
reconstructs previously known behavior rather than discovering a new untouched
edge. Its results are kept in
[the confirmation-alignment report](reports/usdchf_confirmation_alignment/README.md),
alongside the unsuccessful exit/strictness study.
The explicit M1 profile is stored in
`config/usdchf_m30_research_candidate.json` with dry-run enabled, a separate magic
and isolated state paths. It reproduces the previously known M1-fed model; the
fixed training nomination did not approve replacing the M5 baseline. No active
live profile is changed. Complete the descriptive comparison, without reranking
the frozen selections, using:

```powershell
python -m src.tools.complete_usdchf_alignment --history history/mt5_20261111/USDCHF_extended.json --study-dir reports/usdchf_confirmation_alignment
```

## Training-derived USDCHF long-entry filter

The profit-first follow-up uses USDCHF M30 with explicit M1 confirmation. It fits
two BUY-only H4 trend-strength thresholds from each preceding 365-day training
window, then ranks full strategy replays by net profit after execution costs.
Minimum sample and drawdown constraints remain mandatory; the unfiltered model
is the fallback. The filter defaults to `off`; active profiles and risk settings
are unchanged. Live and replay share the filter and the same closed-bar entry
bias context. Both baseline and candidate are rerun after that context alignment.

The frozen plan, training decisions, cost stress and promotion outcome are in
[the long-entry filter report](reports/usdchf_long_filter/README.md). The dates were
previously examined, so this study is not untouched future validation.

```powershell
python -m src.tools.research_long_filter --history history/mt5_20261111/USDCHF_extended.json --output reports/usdchf_long_filter --workers 6
python -m src.tools.render_long_filter_report reports/usdchf_long_filter/report.json
```

These commands use saved history and block broker initialization and trading.

## USDCHF direction, spread and exit comparison

The next frozen study compares three separate ideas on USDCHF M30 / M1:
BUY-only versus SELL-only setups, stricter entry spread caps (1.2 or 0.9 pips),
and tighter trailing gaps (0.75R or 0.5R with the original 1R activation).
Each idea has two predeclared settings plus the common baseline; no combinations
are created after observing results. Position sizing, initial stops, daily loss
and portfolio guards are preserved. Active configurations are unchanged.

See [the three-idea comparison](reports/usdchf_three_ideas/README.md) for all
cost-aware results, the descriptive profit winner, frozen training nominations,
promotion gates and independently audited test trades. Historical winners are
kept separate from evidence supporting a training-selected upgrade.

```powershell
python -m src.tools.research_usdchf_three_ideas --history history/mt5_20261111/USDCHF_extended.json --output reports/usdchf_three_ideas --workers 6
python -m src.tools.render_usdchf_three_ideas reports/usdchf_three_ideas/report.json
```

Replay now defaults to the configured `trade_side_filter`, matching live.
`backtest_mt5 --side` is an explicit research override. Live and replay share
the same finite, nonnegative spread-cap check, including arithmetic tolerance
at the exact boundary. All study models are rerun with these corrections.

## Three-pair H1/H4 research

The next study freezes two new signal models: an H1 EMA pullback/reclaim in the
H4 trend direction, and an H1 20-bar range breakout confirmed by a following
retest, also aligned with H4. Each has one declared setting, applied separately
to EURUSD, GBPUSD and USDCHF. They share their signal function between live and
backtest. The original USDCHF M30/M1 logic, applied with common settings to each
pair, is a reference; original EURUSD/GBPUSD live branches are not replaced.

Initial risk, stops, targets, trailing, sessions, spread caps and daily/exposure
guards remain the same. Native histories cover the same dates; all pairs' prior
training nominations are locked before any test outcomes. Every pair/model is
an independent EUR 10,000 simulation, not a combined portfolio. Swap/overnight
financing is not modeled and overnight trade counts are disclosed.

See [the three-pair H1/H4 report](reports/fx_htf/README.md) for the full comparison,
cost stress, selection evidence, limitations and independently audited trades.

```powershell
python -m src.tools.research_fx_htf --workers 4
python -m src.tools.render_fx_htf reports/fx_htf/report.json
```

These commands use saved histories and block broker connections and orders.
New modes are disabled in all active profiles. Historical gate passes do not
authorize live deployment or establish future profitability.

## Offline USDCHF sizing sensitivity

The risk-budget study compares 0.1%, 0.2%, 0.3% and 0.5% on the original M30/M1
reference and its previously tested 0.9-pip spread variant. Maximum lot stays
0.05; initial stops, exits, daily and portfolio guards are unchanged. The study
does not select or apply a live risk level. It includes the earlier continuous
losing year, the twelve monthly test windows and doubled commission/slippage.

See [the sizing sensitivity report](reports/usdchf_risk_levels/README.md) for
actual capped entry risk, volume distributions, realized drawdowns, losing
streaks and independently reconstructed costs. Historical profit is not simply
multiplied. Swap/overnight financing remains excluded for prior comparability.

```powershell
python -m src.tools.research_risk_levels --workers 6
python -m src.tools.render_risk_levels reports/usdchf_risk_levels/report.json
```

These commands use saved history, block broker/order methods and never update
active settings.

## Confirmation modes
- `none`: enter immediately on sweep (baseline behavior).
- `c3`: wait for a strong C2 candle and a valid C3 close.
- `c4`: wait for C3 and then C4 continuation close.
- `cisd`: wait for lower-timeframe displacement/structure confirmation after sweep.
- `sweep_displacement_mss`: require a significant sweep, anti-chop pass, lower-timeframe displacement, and BOS-style close through recent structure.

## Entry model
- Sweep remains necessary, but not sufficient.
- New setup pipeline:
  1. detect liquidity sweep
  2. reject weak/insignificant sweeps
  3. reject local chop/range conditions
  4. require lower-timeframe displacement
  5. require explicit BOS / structure break confirmation
  6. consume the semantic setup key after trade so the same zone does not retrigger repeatedly
- Demo/default risk protection uses:
  - `per_trade_loss_guard_mode = "position_risk"`
  - `per_trade_loss_risk_multiple = 1.0`
