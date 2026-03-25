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
pip install MetaTrader5 pytest
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
