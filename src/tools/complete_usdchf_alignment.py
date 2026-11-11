"""Descriptive comparison of both predeclared confirmation models; never reranks selections."""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
from typing import Callable

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import load_history
from src.tools.backtest_mt5 import run_backtest
from src.tools.research_usdchf_m30 import _forbid_broker, confirmation_candidates
from src.tools.walk_forward import default_config_paths, discover_branches, trade_metrics


def compare_declared(report: dict, replay: Callable) -> dict:
    """Add descriptive and stress metrics while preserving the frozen policy and decision."""
    if report["plan"].get("study") != "confirmation_alignment":
        raise ValueError("Only the predeclared two-model alignment study is supported")
    result = deepcopy(report)
    plan = report["plan"]
    folds = plan["folds"]
    confirmation = [f for f in folds if f["index"] in plan["confirmation_folds"]]
    costs, stress = ExecutionCosts(**plan["costs"]), ExecutionCosts(**plan["stress_costs"])
    def summary(names: dict[int, str], windows: list[dict], scenario: ExecutionCosts) -> dict:
        trades = [trade for fold in windows for trade in replay(names[fold["index"]], fold, scenario)]
        return trade_metrics(trades, 10000)
    result["declared_comparison"] = {}
    for variant in plan["variants"]:
        name = variant["name"]
        names = {fold["index"]:name for fold in folds}
        result["declared_comparison"][name] = {
            "aggregate":summary(names,folds,costs),
            "confirmation":summary(names,confirmation,costs),
            "stress_confirmation":summary(names,confirmation,stress),
        }
    adaptive = {int(index):name for index,name in report["locked_selections"]["adaptive"].items()}
    result["adaptive_stress_confirmation"] = summary(adaptive,confirmation,stress)
    result["descriptive_comparison_notice"] = (
        "Both configurations were declared and their historical outcomes already known. "
        "This completes their descriptive comparison and checks adaptive cost sensitivity; "
        "it does not change nominations, promotion gates or the original promotion decision."
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history",type=Path,required=True)
    parser.add_argument("--study-dir",type=Path,default=Path("reports/usdchf_confirmation_alignment"))
    args = parser.parse_args()
    _forbid_broker()
    report_path = args.study_dir/"report.json"
    report = json.loads(report_path.read_text())
    history = load_history(args.history)["USDCHF"]
    if history.digest() != report["plan"]["history_sha256"]:
        raise ValueError("History does not match the registered study snapshot")
    source = next(branch for branch in discover_branches(default_config_paths())
                  if branch.branch_id == report["plan"]["baseline_branch"])
    variants = {v.name:v.settings for v in confirmation_candidates(source.symbol)}
    cache = {}
    def replay(name: str, fold: dict, costs: ExecutionCosts) -> list:
        key = (name,fold["index"],json.dumps(asdict(costs),sort_keys=True))
        if key not in cache:
            start,end = datetime.fromisoformat(fold["test_start"]),datetime.fromisoformat(fold["test_end"])
            _,trades = run_backtest(source.config,variants[name],start,end,initial_equity=10000,
                                    costs=costs,history=history,end_exclusive=True)
            cache[key] = trades
            print("Compared",name,"fold",fold["index"],"commission",costs.commission_per_lot,flush=True)
        return cache[key]
    result = compare_declared(report,replay)
    if result["locked_selections"] != report["locked_selections"] or result["promotion_checks"] != report["promotion_checks"]:
        raise AssertionError("Descriptive completion must not alter the selection procedure")
    report_path.write_text(json.dumps(result,indent=2,allow_nan=False),encoding="utf-8")
    print("FINISHED",json.dumps({"declared":result["declared_comparison"],
                                 "adaptive_stress":result["adaptive_stress_confirmation"]}),flush=True)


if __name__ == "__main__":
    main()
