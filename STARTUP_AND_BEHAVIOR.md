# Start It

From `I:\mt5_liquidity_codex_migration`:

1. Create and activate a venv.
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

2. Install dependencies.
```powershell
pip install MetaTrader5 pytest
```

3. Create the runtime config from the example.
```powershell
Copy-Item config\settings.example.json config\settings.json
```

4. Keep `dry_run` enabled at first in `config/settings.json`.
`dry_run: true` means it will analyze and log, but not send live orders.

5. Make sure the MT5 desktop terminal is open and logged into the trading account.
The bot uses the Python `MetaTrader5` package through `src/execution/mt5_adapter.py`, and `mt5.initialize()` must succeed.

6. Run the bot.
```powershell
python -m src.engine.orchestrator
```

The default config path is `config/settings.json`, as wired in `src/engine/orchestrator.py`.

# What It Does

The bot is a liquidity-sweep strategy runner with risk-first controls.

Main behavior:
- Reads market bars from MT5 for each configured symbol/timeframe.
- Builds pivot-based liquidity levels.
- Detects sweep signals around those levels.
- Optionally requires confirmation: `none`, `c3`, `c4`, or `cisd`.
- Applies bias and order-block filters before entry.
- Sizes positions by risk percentage and stop distance.
- Sends market orders through MT5 with fill-mode fallback.
- Tracks open positions and enforces hard risk exits.
- Persists state in SQLite so restart recovery is safe.

Core files:
- Strategy logic: `src/strategy/liquidity.py`
- Confirmation logic: `src/strategy/confirmations.py`
- Filters: `src/strategy/filters.py`
- Risk sizing: `src/risk/sizing.py`
- Runtime loop: `src/engine/orchestrator.py`

# Risk Controls It Enforces

From `src/services/config.py` and `src/engine/orchestrator.py`:

- session filter
- max spread filter
- cooldown between entries
- one-position-per-symbol
- daily loss guard
- per-trade hard close guard
- max total open positions
- max total open risk percent
- restart-safe retry state for forced closes

# Persistence / Recovery

It writes:
- SQLite state DB: pending setups, open-position tracking, guards, counters, retries, bar markers
- CSV event log: runtime and recovery events

Relevant files:
- DB/repository: `src/persistence/db.py`, `src/persistence/repository.py`
- Recovery: `src/persistence/recovery.py`

Startup flow is explicit:
1. load local SQLite state
2. load MT5 broker snapshot and reconcile
3. rebuild in-memory state
4. start loop

MT5 is treated as source of truth for open positions.

# What Files You Will See After Running

- `bot_state.sqlite3`
- `bot_events.csv`
- archive files under `state_archives\` if retention runs

# Before Live Trading

Change `dry_run` to `false` only after you validate:
- symbol names
- broker spreads
- stop/TP behavior
- allowed sessions
- magic numbers
- lot sizing and risk limits
