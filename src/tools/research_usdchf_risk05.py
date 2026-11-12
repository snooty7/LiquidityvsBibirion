"""Matched EUR10k/0.5% USDCHF comparison and separate new-entry prototype tests."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import datetime
import hashlib
import json
from pathlib import Path

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import load_history
from src.backtesting.overnight import OvernightPolicy
from src.backtesting.scalping import ScalpPolicy
from src.backtesting.swaps import SwapModel, rates_from_snapshot, weekday_weights
from src.strategy.fast_scalp import MODELS
from src.tools import research_fast_scalp_entries as fast
from src.tools.research_no_overnight import worker as legacy_worker
from src.tools.research_spread_resilience import configurations
from src.tools.research_swap_2k import initialize as legacy_initialize
from src.tools.research_usdchf_m30 import _forbid_broker
from src.tools.research_usdchf_three_ideas import register
from src.tools.walk_forward import RISK_KEYS, default_config_paths, discover_branches, history_coverage

CAPITAL = 10000.0
RISK_PCT = .5
WINDOWS = {"earlier": ("2024-11-15T00:00:00+00:00", "2025-11-15T00:00:00+00:00"),
           "later": ("2025-11-16T00:00:00+00:00", "2026-11-11T00:00:00+00:00"),
           "full": ("2024-11-15T00:00:00+00:00", "2026-11-11T00:00:00+00:00")}


def settings(source, info):
    """Align both old paths to 0.5%; keep new entries separate and risk-sized."""
    legacy = replace(configurations(source.symbol)["trail_later_1_5"], risk_pct=RISK_PCT)
    runtime = replace(source.config.runtime, max_total_open_risk_pct=RISK_PCT)
    scalp = fast.configurations_for_pair(legacy, "USDCHF", info.volume_max)
    return replace(source.config, runtime=runtime, symbols=(legacy,)), legacy, scalp


def legacy_task(variant, offset, phase, stress, app, cfg, swap):
    """The matched old paths differ solely by SELL pre-rollover policy."""
    start, end = (datetime.fromisoformat(v) for v in WINDOWS[phase])
    name = f"{variant}_gmt{offset}"+("_stress" if stress else "")
    carry = replace(swap, timezone=f"Etc/GMT-{offset}", debit_multiplier=2 if stress else 1)
    policy = None if variant == "original" else OvernightPolicy(("SELL",), carry.timezone)
    return (name, phase, app, cfg, start, end,
            ExecutionCosts("historical", 2, 7, .4) if stress else ExecutionCosts(), carry, CAPITAL, policy)


def run(history_path, snapshot_path, output, workers=6):
    """Freeze both protocols before paired tests; never connect to a terminal."""
    _forbid_broker()
    history = load_history(history_path)["USDCHF"]
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    source = next(b for b in discover_branches(default_config_paths()) if b.branch_id == "92024-USDCHF-M30-3c27c3d9")
    app, legacy, scalp = settings(source, history.symbol_info)
    for cfg in (legacy, scalp):
        for start, end in WINDOWS.values():
            problem = history_coverage(history, cfg, datetime.fromisoformat(start), datetime.fromisoformat(end), max_gap_days=4)
            if problem:
                raise ValueError(problem)
    raw = snapshot["symbols"]["USDCHF"]
    buy, sell = rates_from_snapshot(raw, history.symbol_info, snapshot["account_currency"])
    swap = SwapModel(buy, sell, "Etc/GMT-3", weekday_weights(raw, 3))
    common = {"capital": CAPITAL, "risk_pct": RISK_PCT, "windows": WINDOWS,
        "runtime": {k: getattr(app.runtime, k) for k in RISK_KEYS},
        "history_file": history_path.name, "history_digest": history.digest(),
        "symbol_info": asdict(history.symbol_info), "snapshot": snapshot,
        "swaps": asdict(swap), "triple_day_override": 3,
        "costs": asdict(ExecutionCosts()), "stress_costs": asdict(ExecutionCosts("historical", 2, 7, .4)),
        "code_digest": hashlib.sha256(b"".join(p.read_bytes() for p in sorted(Path("src").rglob("*.py")))).hexdigest(),
        "limitations": ["Historical dates and prior strategy outcomes have been examined repeatedly; this is exploratory validation, not an untouched holdout.",
            "Current swap snapshot held constant over history, with historical constant EUR tick valuation. Daily historical financing and conversion rates unavailable.",
            "MT5 returned invalid triple-day code7; explicit Wednesday triple assumption retained. Primary broker midnight GMT+3 with GMT+2 sensitivity; historical clock/DST policy not reconstructed.",
            "Stress doubles commissions, adverse market/stop slippage and negative swap debits, leaves credits unchanged. Observed spreads unchanged; fallback1 to2 pips.",
            "Independent continuous EUR10k accounts per window/model; no monthly resets or concurrent portfolio aggregation. Drawdown samples M1-close equity and actual fills; intrabar loss can be larger.",
            "Historical margin, execution latency, missing liquidity, tick paths and changing broker stop/volume constraints not reconstructed. No live settings, bot or orders."]}
    legacy_plan = {**common, "group": "matched_old_entries", "settings": asdict(legacy),
        "variants": {"original": "Original M30/M1 entries, initial20-pip SL,2R TP,1.5R activation/1R trailing gap; overnight allowed",
                     "sell_flat": "Exactly identical entries/risk/exits except SELL closed at first M1 open at/after23:55 broker time, with SELL entry blackout until midnight. BUY unchanged; actual gap financing retained."},
        "comparison": "No selection or parameter optimization; replay both fixed variants with both cost levels, both clocks and every window before ranking."}
    fast_plan = {**common, "group": "separate_new_M1_M5_entries", "settings": asdict(scalp), "models": list(MODELS),
        "entry_definitions_source": "src/strategy/fast_scalp.py; unchanged thresholds from prior entry study",
        "rules": "M1 decisions, closed M5 EMA20/50 trend and slope, causal sweep/reclaim/displacement, structure6-15 raw pips plus0.2 pip padding. Spread cap0.7, initial2R target and1.5R/1R trailing. Both sides30-minute cap, weekday05:00-18:00 UTC entries and flat by19:00. Full0.5% price-risk budget with recorded broker volume ceiling, not arbitrary lots. Original cooldown/daily/single-position protection retained.",
        "selection": "For USDCHF nominate highest earlier stressed net among positive, participating, zero-financing/no-overnight candidates; otherwise cash. Tie lower sampled drawdown then name. Lock before later/full new-entry outcomes. All three models and both cost levels reported; not mixed into old-path ranking.",
        "clock_sensitivity": "Primary GMT+3 swap enabled. Audit entire positions under GMT+2 as well; if no events under either and the UTC exit policy is fixed, clock is path-equivalent. Retain and flag any financing violation."}
    legacy_output, fast_output = output/"legacy", output/"fast_entries"
    register(legacy_plan, legacy_output)
    register(fast_plan, fast_output)
    def execute(tasks, pool, worker, plan, records, destination):
        futures = [pool.submit(worker, t) for t in tasks]
        for i, future in enumerate(as_completed(futures), 1):
            record = future.result()
            records.setdefault(record["scenario"], {})[record["window"]] = record
            (destination/"results.partial.json").write_text(json.dumps({"plan": plan, "results": records}, indent=2, allow_nan=False), encoding="utf-8")
            print(plan["group"], record["scenario"], record["window"], round(record["metrics"]["net_pnl"], 2), i, "/", len(tasks), flush=True)
    old_records = {}
    tasks = [legacy_task(v, o, p, s, app, legacy, swap) for v in legacy_plan["variants"]
             for o in (3, 2) for p in WINDOWS for s in (False, True)]
    with ProcessPoolExecutor(max_workers=workers, initializer=legacy_initialize, initargs=(str(history_path),)) as pool:
        execute(tasks, pool, legacy_worker, legacy_plan, old_records, legacy_output)
    (legacy_output/"results.partial.json").replace(legacy_output/"report.json")
    paths = {"USDCHF": str(history_path.resolve())}
    def fast_task(model, phase, stress):
        start, end = (datetime.fromisoformat(v) for v in WINDOWS[phase])
        name = model+("_stress" if stress else "")
        return "USDCHF", model, (name, phase, replace(app, symbols=(scalp,)), scalp, start, end,
            ExecutionCosts("historical", 2, 7, .4) if stress else ExecutionCosts(),
            replace(swap, debit_multiplier=2 if stress else 1), CAPITAL, ScalpPolicy(30))
    new_records = {}
    with ProcessPoolExecutor(max_workers=workers, initializer=fast.initialize, initargs=(paths,)) as pool:
        execute([fast_task(m, "earlier", True) for m in MODELS], pool, fast.worker, fast_plan, new_records, fast_output)
        selected, ranking = fast.nominate({m: new_records[m+"_stress"]["earlier"] for m in MODELS})
        (fast_output/"locked_selection.json").write_text(json.dumps({"selected": selected, "ranking": ranking,
            "fallback": "cash" if selected is None else None}, indent=2), encoding="utf-8")
        print("LOCKED_NEW_ENTRIES", selected, flush=True)
        execute([fast_task(m, p, s) for m in MODELS for p in WINDOWS for s in (False, True)
                 if (p, s) != ("earlier", True)], pool, fast.worker, fast_plan, new_records, fast_output)
    (fast_output/"results.partial.json").replace(fast_output/"report.json")
    print("COMPLETED:24 matched old-path accounts and18 separate new-entry accounts", flush=True)
    return old_records, new_records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, default=Path("reports/fx_intraday_scalping/swap_snapshot.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/usdchf_10k_risk05"))
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("Positive worker count required")
    run(args.history, args.snapshot, args.output, args.workers)
