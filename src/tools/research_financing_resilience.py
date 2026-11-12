"""Predeclared, isolated improvements to the old USDCHF M30/M1 strategy."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import datetime
import hashlib
import json
from pathlib import Path

from src.backtesting.financing_exits import FinancingExitPolicy, LateSellEntryPolicy
from src.backtesting.history import load_history
from src.backtesting.swaps import SwapModel
from src.tools.research_no_overnight import worker as replay_worker
from src.tools.research_swap_2k import initialize
from src.tools.research_usdchf_m30 import _forbid_broker
from src.tools.research_usdchf_risk05 import WINDOWS, legacy_task, settings
from src.tools.research_usdchf_three_ideas import register
from src.tools.walk_forward import RISK_KEYS, default_config_paths, discover_branches

VARIANTS = {
    "original": "Unchanged old M30/M1, overnight allowed",
    "sell_flat": "Known control: SELL flat five minutes before each broker midnight",
    "triple_exit": "SELL flat five minutes before a triple-weight rollover only",
    "one_unit_carry": "SELL allowed one ordinary carry unit per position; exit before cumulative units exceed one",
    "avoid_late_sell_entries": "Block new SELL entries in final90minutes before broker midnight; existing positions unchanged",
    "trail_gap_0_75": "Original1.5R activation, tighter0.75R trailing gap; overnight allowed",
}
ADDED_SOURCES = {"src/backtesting/financing_exits.py", "src/tools/research_financing_resilience.py"}


def normalize(value):
    """Compare JSON protocols without tuple/list artifacts."""
    return json.loads(json.dumps(value, allow_nan=False))


def task(variant, offset, phase, stress, app, cfg, swaps):
    """Change exactly one exit or entry rule; preserve sizing and risk guards."""
    result = list(legacy_task("original" if variant != "sell_flat" else variant,
                              offset, phase, stress, app, cfg, swaps))
    result[0] = f"{variant}_gmt{offset}" + ("_stress" if stress else "")
    if variant in {"triple_exit", "one_unit_carry"}:
        result[9] = FinancingExitPolicy(("SELL",), result[7].timezone, 5,
            "triple_only" if variant == "triple_exit" else "one_unit", tuple(swaps.weekday_weights))
    elif variant == "avoid_late_sell_entries":
        result[9] = LateSellEntryPolicy(("SELL",), result[7].timezone)
    elif variant == "trail_gap_0_75":
        result[3] = replace(cfg, trailing_gap_r=.75)
        result[2] = replace(app, symbols=(result[3],))
    elif variant not in {"original", "sell_flat"}:
        raise ValueError("Unknown variant")
    return tuple(result)


def worker(job):
    """Reuse guarded replay and audit new financing deadlines at actual fills."""
    record = replay_worker(job)
    policy = job[9]
    record["policy_exits"] = 0
    for trade in record["trades"]:
        if trade["reason"] in {"triple_swap_exit", "carry_budget_exit"}:
            entry = int(datetime.fromisoformat(trade["entry_time_utc"]).timestamp())
            closed = int(datetime.fromisoformat(trade["exit_time_utc"]).timestamp())
            if policy is None or not policy.exit_due(trade["side"], entry, closed):
                raise ValueError("Premature financing exit")
            record["policy_exits"] += 1
    return record


def nominate(records):
    """Use earlier GMT+3 stressed results only, including both controls."""
    ranking = sorted(VARIANTS, key=lambda v: (
        -records[v+"_gmt3_stress"]["earlier"]["metrics"]["net_pnl"],
        records[v+"_gmt3_stress"]["earlier"]["account"]["m1_close_drawdown"], v))
    return ranking[0], ranking


def run(history_path, reference_path, output, workers=6):
    """Freeze hypotheses before outcomes; use archived data without MT5 access."""
    _forbid_broker()
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    old = reference["plan"]
    history = load_history(history_path)["USDCHF"]
    source = next(b for b in discover_branches(default_config_paths()) if b.branch_id == "92024-USDCHF-M30-3c27c3d9")
    app, cfg, _ = settings(source, history.symbol_info)
    existing_digest = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(Path("src").rglob("*.py"))
        if p.as_posix() not in ADDED_SOURCES)).hexdigest()
    if (existing_digest != old["code_digest"] or history.digest() != old["history_digest"]
        or normalize(asdict(cfg)) != old["settings"]
        or normalize({k: getattr(app.runtime, k) for k in RISK_KEYS}) != old["runtime"]):
        raise ValueError("Cached controls cannot be reused: source/history/settings differ")
    swaps = SwapModel(**{**old["swaps"], "weekday_weights": tuple(old["swaps"]["weekday_weights"])})
    plan = {**{k: v for k, v in old.items() if k not in {"registered_at_utc", "variants", "comparison", "code_digest"}},
        "variants": VARIANTS, "group": "old_M30_M1_financing_resilience",
        "reference_report_digest": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
        "control_reuse": "24 unchanged accounts reused only after exact original-source, history and risk/signal configuration checks",
        "code_digest": hashlib.sha256(b"".join(p.read_bytes() for p in sorted(Path("src").rglob("*.py")))).hexdigest(),
        "selection": "Nominate highest earlier GMT+3 stressed net, including controls; ties lower M1 drawdown then name. Earlier may remain negative. Lock before later/full new-model results. All results disclosed; reused dates are not untouched holdout.",
        "success_diagnostics": "Full normal/stressed positive under both clocks; later stress positive; compare stressed net with original and known SELL-flat control. Do not replace locked nominee using later results.",
        "live_status": "Research policies only; core replay and live configurations unchanged; terminal initialization/order APIs forbidden."}
    register(plan, output)
    records = normalize(reference["results"])
    jobs = [task(v, o, p, s, app, cfg, swaps) for v in VARIANTS if v not in {"original", "sell_flat"}
            for o in (3, 2) for p in WINDOWS for s in (False, True)]
    def execute(items, pool):
        for future in as_completed([pool.submit(worker, j) for j in items]):
            record = future.result()
            records.setdefault(record["scenario"], {})[record["window"]] = record
            (output/"results.partial.json").write_text(json.dumps({"plan": plan, "results": records}, indent=2, allow_nan=False), encoding="utf-8")
            print(record["scenario"], record["window"], round(record["metrics"]["net_pnl"], 2), flush=True)
    with ProcessPoolExecutor(max_workers=workers, initializer=initialize, initargs=(str(history_path),)) as pool:
        execute([j for j in jobs if j[1] == "earlier" and j[0].endswith("gmt3_stress")], pool)
        selected, ranking = nominate(records)
        (output/"locked_selection.json").write_text(json.dumps({"selected": selected, "ranking": ranking,
            "basis": "earlier GMT+3 stressed only"}, indent=2), encoding="utf-8")
        print("LOCKED", selected, flush=True)
        execute([j for j in jobs if not (j[1] == "earlier" and j[0].endswith("gmt3_stress"))], pool)
    (output/"results.partial.json").replace(output/"report.json")
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--reference", type=Path, default=Path("reports/usdchf_10k_risk05/legacy/report.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/usdchf_risk05_cost_resilience"))
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("Positive worker count required")
    run(args.history, args.reference, args.output, args.workers)
