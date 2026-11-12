"""Frozen comparison of two pre-rollover exit hypotheses and the existing candidate."""
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
from src.backtesting.swaps import SwapModel
from src.tools.research_spread_resilience import configurations
from src.tools.research_swap_2k import initialize, worker as replay_worker
from src.tools.research_usdchf_m30 import _forbid_broker
from src.tools.research_usdchf_three_ideas import register
from src.tools.walk_forward import RISK_KEYS, default_config_paths, discover_branches


def audit_baseline(records, previous, scenarios):
    """Compare serialized ledgers, treating JSON tuple/list conversion consistently."""
    normalize = lambda value: json.loads(json.dumps(value, allow_nan=False))
    for scenario in scenarios:
        for phase, reference in previous["results"][scenario].items():
            actual = records["baseline_"+scenario][phase]
            for key, value in reference.items():
                if key != "scenario" and normalize(actual[key]) != value:
                    raise ValueError(f"Baseline changed: {scenario}/{phase}/{key}")


def worker(task):
    """Audit cutoff execution, entry blackout and remaining financing after quote gaps."""
    record = replay_worker(task)
    policy = task[9]
    record["pre_rollover_exits"] = sum(t["reason"] == "pre_rollover_exit" for t in record["trades"])
    affected = [t for t in record["trades"] if policy and t["side"] in policy.sides]
    record["affected_overnight_trades"] = sum(bool(t["swap_events"]) for t in affected)
    record["affected_swap_net"] = sum(t["swap_money"] for t in affected)
    for trade in affected:
        entry = int(datetime.fromisoformat(trade["entry_time_utc"]).timestamp())
        exit_time = int(datetime.fromisoformat(trade["exit_time_utc"]).timestamp())
        if policy.blocks_entry(trade["side"], entry):
            raise ValueError("Position entered during flattening blackout")
        if trade["reason"] == "pre_rollover_exit" and not policy.exit_due(trade["side"], entry, exit_time):
            raise ValueError("Position flattened before the declared deadline")
    return record


def run(history_path, previous_report, output, workers=6):
    """Register hypotheses before running all unchanged normal/stressed scenarios."""
    _forbid_broker()
    previous = json.loads(previous_report.read_text(encoding="utf-8"))
    original = previous["plan"]
    history = load_history(history_path)["USDCHF"]
    if history.digest() != original["history_digest"]:
        raise ValueError("Historical input differs from the reference study")
    source = next(b for b in discover_branches(default_config_paths())
                  if b.branch_id == "92024-USDCHF-M30-3c27c3d9")
    cfg = replace(configurations(source.symbol)["trail_later_1_5"], risk_pct=.75)
    app = replace(source.config, runtime=replace(source.config.runtime, max_total_open_risk_pct=.75))
    normalize = lambda v: json.loads(json.dumps(v))
    runtime = {k: getattr(app.runtime, k) for k in RISK_KEYS}
    if normalize(asdict(cfg)) != original["settings"] or normalize(runtime) != original["runtime"]:
        raise ValueError("Reference signal/risk settings changed")
    names = ("baseline", "sell_flat", "all_flat")
    plan = {"capital": 10000, "risk_pct": .75, "settings": asdict(cfg), "runtime": runtime,
        "registration_amendment": "Initial registration retained in initial_registration.json. After all initial replays, baseline verification compared in-memory swap-event tuples against JSON lists and rejected identical ledgers before saving. Only JSON-normalized verification and recoverable checkpoint saving were fixed; signal, exit, sizing, costs, windows, hypotheses and ranking are unchanged. Replays repeated under this source digest.",
        "variants": {"baseline": "Existing 1.5R trailing, overnight allowed",
            "sell_flat": "SELL only: flatten at first quote at/after 23:55 broker time; BUY unchanged",
            "all_flat": "BUY and SELL: flatten at first quote at/after 23:55 broker time"},
        "entry_rule": "Affected sides cannot enter 23:55 inclusive to midnight exclusive; otherwise original signals, sessions, cooldown and risk checks. No automatic reopening of a closed trade.",
        "fill_rule": "First available M1 bar open at/after cutoff; actual bid/ask spread, commission and adverse market slippage. Never use a later quote to fabricate a prior fill. Quote gaps can cause late exits and real financing; daily protection has priority.",
        "windows": original["windows"], "cost_scenarios": {k: v for k, v in original["scenarios"].items() if k.startswith("swap_")},
        "snapshot": original["swap_snapshot"], "triple_day_override": original["triple_day_override"],
        "history_digest": history.digest(),
        "reference_report_digest": hashlib.sha256(previous_report.read_bytes()).hexdigest(),
        "code_digest": hashlib.sha256(b"".join(p.read_bytes() for p in sorted(Path("src").rglob("*.py")))).hexdigest(),
        "selection": "No parameter search, optimized cutoff or combinations. Run both predeclared hypotheses and baseline under both clocks, both cost levels and all three windows; report every result. Full stressed profit ranking is descriptive only, not untouched validation.",
        "limitations": original["limitations"] + ["Five-minute deadline is a fixed execution convention, not an optimized parameter. Additional exits may discard winners and increase turnover. Rules are paper-only and not implemented in live execution."]}
    output.mkdir(parents=True, exist_ok=True)
    register(plan, output)
    jobs = []
    for variant in names:
        for scenario, values in plan["cost_scenarios"].items():
            swap_values = dict(values["swaps"])
            swap_values["weekday_weights"] = tuple(swap_values["weekday_weights"])
            swaps = SwapModel(**swap_values)
            policy = None if variant == "baseline" else OvernightPolicy(
                ("SELL",) if variant == "sell_flat" else ("BUY", "SELL"), swaps.timezone)
            for phase, (start, end) in plan["windows"].items():
                jobs.append((variant+"_"+scenario, phase, app, cfg, datetime.fromisoformat(start),
                    datetime.fromisoformat(end), ExecutionCosts(**values["costs"]), swaps, 10000, policy))
    records = {}
    with ProcessPoolExecutor(max_workers=workers, initializer=initialize, initargs=(str(history_path),)) as pool:
        futures = [pool.submit(worker, task) for task in jobs]
        for index, future in enumerate(as_completed(futures), 1):
            result = future.result()
            records.setdefault(result["scenario"], {})[result["window"]] = result
            (output/"results.partial.json").write_text(json.dumps({"plan": plan, "results": records},
                indent=2, allow_nan=False), encoding="utf-8")
            print(index, "/", len(jobs), result["scenario"], result["window"],
                  round(result["metrics"]["net_pnl"], 2), flush=True)
    # The optional policy must leave the reference path exactly unchanged.
    audit_baseline(records, previous, plan["cost_scenarios"])
    (output/"results.partial.json").replace(output/"report.json")
    print("COMPLETED: all baseline results match the preceding swap study", flush=True)
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--reference", type=Path, default=Path("reports/usdchf_10k_swap/report.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/usdchf_10k_no_overnight"))
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("Positive worker count required")
    run(args.history, args.reference, args.output, args.workers)
