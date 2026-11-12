"""Three isolated profit hypotheses on the fixed SELL-flat EUR10k candidate."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime
import hashlib
import json
from pathlib import Path

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import load_history
from src.backtesting.overnight import OvernightPolicy
from src.backtesting.swaps import SwapModel
from src.tools.research_no_overnight import audit_baseline, worker
from src.tools.research_spread_resilience import configurations as reference_configurations
from src.tools.research_swap_2k import initialize
from src.tools.research_usdchf_m30 import _forbid_broker
from src.tools.research_usdchf_three_ideas import register
from src.tools.walk_forward import RISK_KEYS, default_config_paths, discover_branches


def configurations(base):
    """Change exactly one entry/exit parameter per hypothesis; retain initial risk."""
    return {"baseline": base,
        "spread_0_7": replace(base, max_spread_pips=.7),
        "stronger_confirmation": replace(base, confirmation_displacement_range_multiple=2.0),
        "trailing_gap_1_25": replace(base, trailing_gap_r=1.25)}


def nominate(earlier_stress):
    """Rank earlier stressed net only, tie smaller drawdown then stable name."""
    ranking = sorted(earlier_stress, key=lambda n: (-earlier_stress[n]["metrics"]["net_pnl"],
        earlier_stress[n]["account"]["m1_close_drawdown"], n))
    return ranking[0], ranking


def digest(paths):
    """Hash the exact registered source bytes in stable path order."""
    return hashlib.sha256(b"".join(p.read_bytes() for p in sorted(paths))).hexdigest()


def run(history_path, reference_path, output, workers=6):
    """Freeze changes, nominate before later results, and report every hypothesis."""
    _forbid_broker()
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    old_plan = reference["plan"]
    history = load_history(history_path)["USDCHF"]
    if history.digest() != old_plan["history_digest"]:
        raise ValueError("History differs from the previous frozen study")
    source_paths = list(Path("src").rglob("*.py"))
    old_source_paths = [p for p in source_paths if p.resolve() != Path(__file__).resolve()]
    if digest(old_source_paths) != old_plan["code_digest"]:
        raise ValueError("Existing replay source changed; cached reference cannot be reused")
    source = next(b for b in discover_branches(default_config_paths())
                  if b.branch_id == "92024-USDCHF-M30-3c27c3d9")
    base = replace(reference_configurations(source.symbol)["trail_later_1_5"], risk_pct=.75)
    app = replace(source.config, runtime=replace(source.config.runtime, max_total_open_risk_pct=.75))
    normalize = lambda v: json.loads(json.dumps(v, allow_nan=False))
    runtime = {k: getattr(app.runtime, k) for k in RISK_KEYS}
    if normalize(asdict(base)) != old_plan["settings"] or normalize(runtime) != old_plan["runtime"]:
        raise ValueError("Reference signal/risk settings differ")
    cfgs = configurations(base)
    plan = {"capital": 10000, "risk_pct": .75, "settings": {n: asdict(c) for n, c in cfgs.items()},
        "runtime": runtime, "windows": old_plan["windows"], "cost_scenarios": old_plan["cost_scenarios"],
        "hypotheses": {"baseline": "Existing SELL-flat candidate: spread<=0.9, displacement1.8, trailing gap1R",
            "spread_0_7": "Reject entries with spread above 0.7 pips instead of 0.9; unchanged cost charging",
            "stronger_confirmation": "Displacement range threshold2.0 instead of1.8; require a stronger confirmation",
            "trailing_gap_1_25": "Activation stays1.5R; trail with1.25R gap instead of1R to allow larger winners. Initial SL unchanged; existing SL can only tighten."},
        "overnight": {"sides": ["SELL"], "minutes_before": 5, "entry_blackout": "23:55 inclusive to midnight exclusive; same gap-safe market exits as reference"},
        "selection": "Primary fixed GMT+3 earlier-period stressed net only; highest net, tie lower M1-close drawdown, then name. Include baseline, even if every earlier net is negative. Lock before later/full outcomes. No sample gate, parameter amendments or combinations. All scenarios reported; rankings of full results are descriptive only.",
        "cache": "Reuse all12 previously completed baseline ledgers only after exact source, history, config and runtime verification; rerun all36 alternative scenarios. Baseline is never estimated by scaling or subtracting costs.",
        "snapshot": old_plan["snapshot"], "triple_day_override": old_plan["triple_day_override"],
        "history_digest": history.digest(), "reference_report_digest": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
        "reference_source_digest": digest(old_source_paths), "code_digest": digest(source_paths),
        "limitations": old_plan["limitations"] + ["Older and later data have already been examined repeatedly. Earlier-only nomination is causal within this replay but later results are not an untouched holdout. No promise of live profits or automatic deployment.",
            "Trailed protection never moves away from entry after being tightened; increasing configured gap changes the candidate path before entry, not an already-running live position."]}
    output.mkdir(parents=True, exist_ok=True)
    register(plan, output)
    records = {}
    for scenario in plan["cost_scenarios"]:
        records["baseline_"+scenario] = deepcopy(reference["results"]["sell_flat_"+scenario])
        for record in records["baseline_"+scenario].values():
            record["scenario"] = "baseline_"+scenario
    def save():
        (output/"results.partial.json").write_text(json.dumps({"plan": plan, "results": records}, indent=2, allow_nan=False), encoding="utf-8")
    def task(name, scenario, phase):
        values = plan["cost_scenarios"][scenario]
        swaps_dict = dict(values["swaps"])
        swaps_dict["weekday_weights"] = tuple(swaps_dict["weekday_weights"])
        swaps = SwapModel(**swaps_dict)
        start, end = (datetime.fromisoformat(v) for v in plan["windows"][phase])
        return (name+"_"+scenario, phase, app, cfgs[name], start, end,
                ExecutionCosts(**values["costs"]), swaps, 10000, OvernightPolicy(("SELL",), swaps.timezone))
    def batch(tasks, pool):
        futures = [pool.submit(worker, t) for t in tasks]
        for index, future in enumerate(as_completed(futures), 1):
            result = future.result()
            records.setdefault(result["scenario"], {})[result["window"]] = result
            save()
            print(result["scenario"], result["window"], round(result["metrics"]["net_pnl"], 2), index, "/", len(futures), flush=True)
    alternatives = [n for n in cfgs if n != "baseline"]
    save()
    with ProcessPoolExecutor(max_workers=workers, initializer=initialize, initargs=(str(history_path),)) as pool:
        batch([task(n, "swap_gmt3_stress", "earlier") for n in alternatives], pool)
        selected, ranking = nominate({n: records[n+"_swap_gmt3_stress"]["earlier"] for n in cfgs})
        (output/"locked_selection.json").write_text(json.dumps({"selected": selected, "ranking": ranking,
            "selection_basis": "Earlier GMT+3 stressed net only; locked before later/full alternatives"}, indent=2), encoding="utf-8")
        print("LOCKED:", selected, flush=True)
        batch([task(n, s, phase) for n in alternatives for s in plan["cost_scenarios"] for phase in plan["windows"]
               if (s, phase) != ("swap_gmt3_stress", "earlier")], pool)
    normalized_reference = {"results": {s: reference["results"]["sell_flat_"+s] for s in plan["cost_scenarios"]}}
    audit_baseline(records, normalized_reference, plan["cost_scenarios"])
    (output/"results.partial.json").replace(output/"report.json")
    print("COMPLETED: three hypotheses plus exact cached baseline", flush=True)
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--reference", type=Path, default=Path("reports/usdchf_10k_no_overnight/report.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/usdchf_10k_sell_flat_profit"))
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("Positive worker count required")
    run(args.history, args.reference, args.output, args.workers)
