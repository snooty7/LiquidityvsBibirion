# Adaptive research deployment guide

This release is **offline/observational only**. It does not add an adaptive strategy mode to the live orchestrator, install ML libraries, change production configuration, alter credentials, start MT5 or send trades. Existing strategies retain their dispatch, guards and execution adapter. The adaptive evaluator is broker-independent; a future live adapter is a separate, unimplemented boundary.

The latest [lifecycle validation](10_level_lifecycle_results.md) uses `reports/qait/lifecycle_92001/protocol.json` and `stress_protocol.json`. These supersede the earlier research protocols for the corrected code; original evidence remains available at its frozen source revision. This correction does not change activation or risk settings.

## Defaults and configuration

Omitting `adaptive` preserves a disabled `AdaptiveConfig`. `enabled`, `ml_shadow`, `dynamic_leverage`, `hedging`, break-even, trailing activation and partial activation are all false/zero by default. Enabling dynamic leverage or hedging raises a configuration error. An enabled adaptive observation cannot coexist with `ignore_portfolio_cap` in the loaded profiles.

To inspect settings without starting any process:

```powershell
.venv/Scripts/python.exe -c "from src.services.config import load_config; print(load_config('config/settings.json').adaptive)"
```

The existing settings/example specify `dry_run=false`; do not launch the orchestrator as a way to test research code. No production file needs editing. The research freezer creates an enabled **in-memory override** for its explicit offline run and leaves the original file disabled/unchanged.

Optional observation settings in a separate local research configuration could include:

```json
{
  "adaptive": {
    "enabled": true,
    "ml_shadow": true,
    "entry_timeframe": "M5",
    "context_timeframes": ["H1", "H4"],
    "allow_utc_weekend_gaps": true
  }
}
```

This fragment is not a standalone bot profile or a live activation recipe. `enabled=true` permits the observation UI and evaluator; it creates no adaptive live order route. All original settings still resolve through the existing configuration loader and local override semantics.

## Run the saved-history comparison

From the repository root, the initial protocol was frozen using:

```powershell
.venv/Scripts/python.exe -m src.tools.research_adaptive freeze --config config/settings.json --history history/mt5_20261111/EURUSD.json --magic 92001 --start 2026-10-01 --end 2026-11-01 --train-days 7 --validation-days 3 --test-days 7 --embargo-days 1 --output reports/qait/eurusd_92001/protocol.json
.venv/Scripts/python.exe -m src.tools.research_adaptive run --protocol reports/qait/eurusd_92001/protocol.json --output reports/qait/eurusd_92001/base
```

Run directories and protocol files are never overwritten. For a new experiment use a new protocol/run path. Source/data/config drift invalidates a frozen protocol; register another experiment rather than modifying it in place. The committed protocol identifies the source-code digest, not just a Git commit, and needs the same saved history and effective private configuration to reproduce. Public notification fields are redacted; their hashes still participate in drift checks.

Doubled-cost freeze uses the same arguments plus `--spread-multiplier 2 --commission-per-lot 7 --slippage-pips 0.4`, with `stress_protocol.json` and a distinct `doubled_costs` output. A repeated base run to a new directory should produce an identical `report.json` hash on the same inputs. No network or MT5 is needed for these commands.

## Dashboard integration

The existing dashboard has an optional hidden adaptive panel. Default configurations produce no adaptive field or extra adaptive market-data calls. Enabled observations include regime, timeframe direction, active liquidity, BOS/MSS/sweeps, FVG/OB state, premium/discount context, normalized score/availability, indicative entry/SL/TP, indicative risk, unavailable/shadow ML status and rejection reasons. Proposed prices use the last completed close and are explicitly not executable quotes or preflight approval.

The existing server and static exporter accept `--adaptive-report PATH` to attach test-phase comparison summaries. Their existing MT5 market-data connection behavior remains; they were tested with fake adapters, not started against a terminal during development. Static export preserves the same optional snapshot field and existing chart data. Legacy snapshots without `adaptive` keep the panel hidden.

## Verification

```powershell
.venv/Scripts/python.exe -m pytest -q
node --check dashboard/app.js
node tests/test_adaptive_dashboard.cjs
git diff --check
```

New tests forbid real adapter initialization and order/modify/close methods. They cover causal candles/pivots, missing/stale/gapped/malformed context, score availability, extreme regimes, valid and duplicate proposals, MTF conflicts, risk budgets, broker volume/tick/stop constraints, correlation/concentration, unknown exposure, daily loss, one-way stops, partial accounting, no-op baseline parity, frozen-input drift and observational dashboard behavior. Existing sizing/execution/recovery regressions remain intact. See [results](05_results.md) for observed counts and study results.

## Promotion and rollback boundaries

Promotion beyond research requires account-wide synchronized portfolio replay, marked equity, adequate independent samples/holdout, broker metadata and margin/fill validation through the isolated adapter, and persisted/reconciled live exit milestones. Optional fitted ML additionally needs a purged chronological dataset, calibrated versioned artifacts and an unchanged trading ledger in shadow mode. Missing requirements are not solved by raising score confidence, leverage or risk.

No automatic activation or merge is provided. There is no new live route to turn off. To stop observations, omit the adaptive section or set `enabled=false` in the separate observation profile. To roll back code, review/revert the focused feature commits through normal Git workflow while preserving user settings and databases. This guide does not authorize live trading.
