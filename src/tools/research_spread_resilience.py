"""Frozen cost-resilience comparison for USDCHF spread<=0.9, EUR20k, risk 0.5%."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import load_history
from src.tools.research_loss_reduction import initialize, worker
from src.tools.research_usdchf_m30 import _forbid_broker, study_folds
from src.tools.research_usdchf_three_ideas import register, source_hash
from src.tools.walk_forward import RISK_KEYS, default_config_paths, discover_branches


def configurations(base):
    """Four isolated hypotheses; no combinations, sizing increase or guard relaxation."""
    baseline = replace(base, risk_pct=.5, max_lot=.5, max_spread_pips=.9,
                       cisd_timeframe="M1", cisd_lookback_bars=300)
    return {"baseline": baseline,
            "trail_later_1_5": replace(baseline, trailing_activation_r=1.5),
            "trail_gap_1_25": replace(baseline, trailing_gap_r=1.25),
            "stronger_confirmation": replace(baseline, confirmation_displacement_range_multiple=2),
            "fresh_confirmation": replace(baseline, confirm_expiry_bars=3)}


def nominate(earlier_stress):
    """Choose using earlier stressed outcomes only; later/full outcomes cannot influence it."""
    ranking = sorted(earlier_stress, key=lambda n: (-earlier_stress[n]["metrics"]["net_pnl"],
        earlier_stress[n]["account"]["m1_close_drawdown"], n))
    return ranking[0], ranking


def code_hash():
    paths = [Path(__file__), Path("src/tools/research_loss_reduction.py"), Path("src/tools/research_capital_20k.py")]
    return hashlib.sha256(source_hash().encode()+b"".join(p.read_bytes() for p in paths)).hexdigest()


def make_plan(path):
    source = next(b for b in discover_branches(default_config_paths()) if b.branch_id == "92024-USDCHF-M30-3c27c3d9")
    cfgs = configurations(source.symbol)
    history = load_history(path)["USDCHF"]
    folds = study_folds(365)
    windows = {"earlier": {"start": folds[0].train_start.isoformat(), "end_exclusive": folds[0].train_end.isoformat()},
               "later": {"start": folds[0].test_start.isoformat(), "end_exclusive": folds[-1].test_end.isoformat()},
               "full": {"start": folds[0].train_start.isoformat(), "end_exclusive": folds[-1].test_end.isoformat()}}
    plan = {"registered_at_utc": datetime.now(timezone.utc).isoformat(),
        "objective": "Improve already-known spread<=0.9 model so full-history stressed net stays positive while retaining EUR100-200 successful trades",
        "hypotheses": {"baseline": "Original 1R activation / 1R trailing gap and M1 confirmation",
            "trail_later_1_5": "Activate trailing at 1.5R; original 1R gap",
            "trail_gap_1_25": "Original 1R activation, trailing gap 1.25R; existing SL can only improve",
            "stronger_confirmation": "Displacement range multiple 2.0 instead of 1.8",
            "fresh_confirmation": "Setup expiry 3 M30 bars instead of 5"},
        "settings": {n: asdict(c) for n, c in cfgs.items()},
        "risk_runtime": {k: getattr(source.config.runtime, k) for k in RISK_KEYS},
        "fixed": "EUR20,000 starting balance, 0.5% risk per entry, 0.5 max lot, 20-pip initial SL and 2R initial TP; spread cap 0.9; original daily/portfolio guards, sessions, cooldown and single-position rule. No martingale/averaging or widening existing stops.",
        "windows": windows, "costs": asdict(ExecutionCosts()), "stress_costs": asdict(ExecutionCosts("historical", 2, 7, .4)),
        "selection": "Nominate highest net in earlier-year doubled-cost replay only; tie lower M1-close equity drawdown, then name. Lock before later or full-history replays. Report every hypothesis including rejected nominees; no parameter amendment after outcomes.",
        "success_measure": "Nominee full-history base AND doubled-cost net positive, mean net winner EUR100-200 and at least one winning trade in that band in each scenario; later doubled-cost net also positive with mean winner EUR100-200. Counts and all other outcomes disclosed. Descriptive historical criterion, not live approval.",
        "history_sha256": history.digest(), "symbol_info": asdict(history.symbol_info), "replay_code_sha256": code_hash(),
        "accounting": "Each window is a separate continuous EUR20k account, no monthly resets. Full window carries equity/positions across both years. Drawdown includes open P&L at observed M1 closes and incurred entry commission, with actual simulated fills on exits.",
        "limitations": ["These dates were examined repeatedly in prior research. This is exploratory improvement on reused history; positivity does not prove future profitability.",
            "Only earlier-year stress selects the fixed nominee. The full-history comparison includes selection data and is descriptive, not an untouched holdout.",
            "Historical spreads, assumed commissions/slippage and constant symbol valuation. Swap/overnight financing, latency, historical margin/minimum-stop constraints and full tick paths are not modeled.",
            "Doubled costs means EUR7.00/lot/side commission and 0.4-pip adverse market/stop slippage instead of EUR3.50/0.2 pip. Observed spread is unchanged; missing-spread fallback doubles from 1 to 2 pips.",
            "M1-close drawdown can be smaller than intrabar drawdown. Daily loss guard is a trigger, not a guaranteed loss bound.",
            "Mean winning trade excludes losses; net for all trades, count in target band and mean losing trade are disclosed. No promise that every successful trade earns EUR100-200."],
        "broker_connections": False, "trading_calls": False, "live_settings_changed": False}
    return plan, source.config, cfgs


def run(path, output, workers=4, register_only=False):
    _forbid_broker()
    plan, app, cfgs = make_plan(path)
    plan = register(plan, output)
    if register_only:
        print("Registered four cost-resilience hypotheses plus baseline; risk unchanged", flush=True)
        return plan
    costs, stress = ExecutionCosts(**plan["costs"]), ExecutionCosts(**plan["stress_costs"])
    records = {}
    def task(name, phase):
        window = plan["windows"][phase.removesuffix("_stress")]
        return name, phase, app, cfgs[name], datetime.fromisoformat(window["start"]), datetime.fromisoformat(window["end_exclusive"]), stress if phase.endswith("_stress") else costs
    def batch(items, pool):
        futures = [pool.submit(worker, t) for t in items]
        for index, future in enumerate(as_completed(futures), 1):
            r = future.result()
            records[(r["name"], r["phase"])] = r
            print(r["phase"], r["name"], f"{index}/{len(futures)}", flush=True)
    with ProcessPoolExecutor(max_workers=workers, initializer=initialize, initargs=(str(path),)) as pool:
        batch([task(n, "earlier_stress") for n in cfgs], pool)
        selected, ranking = nominate({n: records[(n, "earlier_stress")] for n in cfgs})
        locked = {"selected": selected, "earlier_stress_ranking": ranking}
        (output/"locked_selection.json").write_text(json.dumps(locked, indent=2), encoding="utf-8")
        print("Locked before later/full outcomes:", selected, flush=True)
        batch([task(n, phase) for phase in ("earlier", "later", "later_stress", "full", "full_stress") for n in cfgs], pool)
    comparison = {n: {phase: records[(n, phase)] for phase in ("earlier", "earlier_stress", "later", "later_stress", "full", "full_stress")} for n in cfgs}
    checks = {}
    for name, phases in comparison.items():
        checks[name] = {"full_base_profitable": phases["full"]["metrics"]["net_pnl"] > 0,
            "full_stress_profitable": phases["full_stress"]["metrics"]["net_pnl"] > 0,
            "later_stress_profitable": phases["later_stress"]["metrics"]["net_pnl"] > 0,
            "winning_trade_goal": all(100 <= phases[p]["mean_winner"] <= 200 and phases[p]["wins_100_to_200"] > 0 for p in ("full", "full_stress", "later_stress"))}
    report = {"plan": plan, "locked_selection": locked, "comparison": comparison,
              "descriptive_checks": checks, "nominee_meets_historical_objective": all(checks[selected].values()),
              "live_settings_changed": False}
    (output/"report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print("FINISHED", json.dumps({"nominee": selected, "checks": checks}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, default=Path("history/mt5_20261111/USDCHF_extended.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/usdchf_spread_resilience"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--register-only", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("workers must be positive")
    run(args.history, args.output, args.workers, args.register_only)


if __name__ == "__main__":
    main()
