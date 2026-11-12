"""Five isolated offline improvements to the EUR10k/0.5% direction adviser."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from src.backtesting.history import load_history
from src.backtesting.swaps import SwapModel
from src.risk.sizing import calc_position_risk_money
from src.strategy.adaptive_direction_agent import AdviceConfig, fit_advice, update_boundary
from src.strategy.cost_aware_agent import ClosedOutcome
from src.tools import backtest_mt5 as replay
from src.tools.research_direction_agent import task as old_task
from src.tools.research_financing_resilience import normalize, worker as replay_worker
from src.tools.research_swap_2k import initialize
from src.tools.research_usdchf_m30 import _forbid_broker
from src.tools.research_usdchf_risk05 import WINDOWS, settings
from src.tools.research_usdchf_three_ideas import register
from src.tools.walk_forward import RISK_KEYS, default_config_paths, discover_branches

VARIANTS = {
    "baseline": "Previous monthly best-side agent:180day window,>=8 trades/side,positive stressed mean netR",
    "weekly": "Only refit cadence changes to Monday00:00 UTC",
    "lookback_90": "Only history window changes to90calendar days; minimum8 unchanged",
    "lookback_365": "Only history window changes to365calendar days; minimum8 unchanged",
    "recent_weighted": "Only mean weighting changes: exponential60day half life,180day window",
    "trail_gap_1_25": "Same monthly advice, only candidate trailing gap changes to1.25R; activation1.5R and initial20pipSL unchanged",
}
NEW_SOURCES = {"src/strategy/adaptive_direction_agent.py", "src/tools/research_agent_improvement.py"}


def advice_config(variant):
    """Return one predeclared parameter change without a combinatorial search."""
    if variant not in VARIANTS:
        raise ValueError("Unknown variant")
    changes = {"weekly": {"cadence": "weekly"}, "lookback_90": {"lookback_days": 90},
        "lookback_365": {"lookback_days": 365}, "recent_weighted": {"half_life_days": 60}}
    return AdviceConfig(**changes.get(variant, {}))


def task(variant, offset, phase, stress, app, cfg, swaps, outcomes=()):
    """Preserve original signals, entry budget and financing/exit execution path."""
    job, _, _ = old_task("agent_best", offset, phase, stress, app, cfg, swaps, outcomes)
    job = list(job)
    job[0] = f"{variant}_gmt{offset}"+("_stress" if stress else "")
    if variant == "trail_gap_1_25":
        job[3] = replace(cfg, trailing_gap_r=1.25)
        job[2] = replace(app, symbols=(job[3],))
    return tuple(job), advice_config(variant), outcomes


@contextmanager
def adviser_gate(outcomes, config):
    """Gate simulated entries only; delegate accepted risk sizing unchanged."""
    original = replay._build_entry_trade
    fits, decisions = {}, []
    def build(cfg, runtime, info, equity, side, timestamp, *args, **kwargs):
        boundary = update_boundary(timestamp, config)
        if boundary not in fits:
            fits[boundary] = fit_advice(outcomes, timestamp, config)
        allowed = side in fits[boundary].allowed_sides
        decisions.append({"time": timestamp, "side": side, "allow": allowed, "fitted_at": boundary})
        if not allowed:
            return None
        return original(cfg, runtime, info, equity, side, timestamp, *args, **kwargs)
    try:
        replay._build_entry_trade = build
        yield fits, decisions
    finally:
        replay._build_entry_trade = original


def worker(item):
    """Replay and retain every decision, then audit successful entries."""
    job, config, outcomes = item
    with adviser_gate(outcomes, config) as (fits, decisions):
        record = replay_worker(job)
    record["agent_fits"] = [asdict(fits[b]) for b in sorted(fits)]
    record["agent_decisions"] = decisions
    for trade in record["trades"]:
        stamp = int(datetime.fromisoformat(trade["entry_time_utc"]).timestamp())
        if trade["side"] not in fits[update_boundary(stamp, config)].allowed_sides:
            raise ValueError("Entry violates locked adviser permission")
    return record


def nominate(records):
    """Select only by earlier stressed net; retain cash if no positive candidate."""
    ranking = sorted(VARIANTS, key=lambda v: (-records[v+"_gmt3_stress"]["earlier"]["metrics"]["net_pnl"],
        records[v+"_gmt3_stress"]["earlier"]["account"]["m1_close_drawdown"], v))
    return (ranking[0] if records[ranking[0]+"_gmt3_stress"]["earlier"]["metrics"]["net_pnl"] > 0 else "cash"), ranking


def run(history_path, reference_path, output, workers=6):
    """Freeze hypotheses, verify cached controls and run without any MT5 connection."""
    _forbid_broker()
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    old = reference["plan"]
    history = load_history(history_path)["USDCHF"]
    source = next(b for b in discover_branches(default_config_paths()) if b.branch_id == "92024-USDCHF-M30-3c27c3d9")
    app, cfg, _ = settings(source, history.symbol_info)
    files = sorted(Path("src").rglob("*.py"))
    digest = lambda paths: hashlib.sha256(b"".join(p.read_bytes() for p in paths)).hexdigest()
    if (digest([p for p in files if p.as_posix() not in NEW_SOURCES]) != old["code_digest"]
        or history.digest() != old["history_digest"] or normalize(asdict(cfg)) != old["settings"]
        or normalize({k: getattr(app.runtime, k) for k in RISK_KEYS}) != old["runtime"]):
        raise ValueError("Reference controls invalid: source/history/settings mismatch")
    swaps = SwapModel(**{**old["swaps"], "weekday_weights": tuple(old["swaps"]["weekday_weights"])})
    training = {}
    for offset in (3, 2):
        trades = reference["results"][f"baseline_gmt{offset}_stress"]["full"]["trades"]
        training[offset] = tuple(ClosedOutcome(int(datetime.fromisoformat(t["exit_time_utc"]).timestamp()), t["side"],
            t["pnl_money"]/calc_position_risk_money(t["entry_price"], t["sl_initial"], t["volume"], history.symbol_info)) for t in trades)
    plan = {**{k: v for k, v in old.items() if k not in {"variants", "selection", "control_reuse", "code_digest", "agent_protocol"}},
        "group": "agent_cadence_memory_weighting_exit", "registered_at_utc": datetime.now(timezone.utc).isoformat(),
        "variants": VARIANTS, "advice_configs": {v: asdict(advice_config(v)) for v in VARIANTS},
        "reference_report_digest": hashlib.sha256(reference_path.read_bytes()).hexdigest(), "code_digest": digest(files),
        "control_reuse": "12 previous agent_best accounts reused after exact previous-source/history/config checks; labels renamed only. Default advice has regression parity with old fit_month(best_only=True).",
        "selection": "Earlier GMT+3 stressed net only, include baseline and cash0. Highest positive net, ties smaller M1 drawdown then name. Lock before later/full new candidates. No combinations or retuning after results; full winners descriptive only.",
        "agent_protocol": "Each declared update fits only shadow reference trades EXITED strictly BEFORE UTC month/Monday boundary within its declared calendar-day window. >=8 per side and positive stressed mean netR, best side only, BUY on tie, otherwise cash. Weighted variant uses2^(-age_days/60). Same stressed shadow labels train normal/stressed runs separately per broker clock. Initial shadow history starts15Nov2024; no invented warmup. Existing trades retain original exits across adviser updates; no account resets.",
        "exit_training": "Trailing-gap hypothesis uses exactly the same original shadow outcomes/advice as baseline, isolating execution of exits; it does not retrain on its own future results. Initial risk and1.5R activation unchanged; shared helper never loosens an already tightened stop.",
        "limitations": old["limitations"]+["Five additional hypotheses on repeatedly examined dates increase selection/overfitting risk; no independent future validation. Weighted means can have fewer effective samples than raw count8; this is an exploratory heuristic, not a statistical confidence guarantee."]}
    register(plan, output)
    records = {}
    for offset in (3, 2):
        for stress in (False, True):
            suffix = f"gmt{offset}"+("_stress" if stress else "")
            records["baseline_"+suffix] = normalize(reference["results"]["agent_best_"+suffix])
            for record in records["baseline_"+suffix].values():
                record["scenario"] = "baseline_"+suffix
    jobs = [task(v, o, p, s, app, cfg, swaps, training[o]) for v in VARIANTS if v != "baseline"
            for o in (3, 2) for p in WINDOWS for s in (False, True)]
    def execute(items, pool):
        for future in as_completed([pool.submit(worker, j) for j in items]):
            record = future.result()
            records.setdefault(record["scenario"], {})[record["window"]] = record
            (output/"results.partial.json").write_text(json.dumps({"plan": plan, "results": records}, indent=2, allow_nan=False), encoding="utf-8")
            print(record["scenario"], record["window"], round(record["metrics"]["net_pnl"], 2), flush=True)
    with ProcessPoolExecutor(max_workers=workers, initializer=initialize, initargs=(str(history_path),)) as pool:
        execute([j for j in jobs if j[0][1] == "earlier" and j[0][0].endswith("gmt3_stress")], pool)
        selected, ranking = nominate(records)
        (output/"locked_selection.json").write_text(json.dumps({"selected": selected, "ranking": ranking,
            "basis": "Earlier GMT+3 stressed only, cash0 benchmark"}, indent=2), encoding="utf-8")
        print("LOCKED", selected, flush=True)
        execute([j for j in jobs if not (j[0][1] == "earlier" and j[0][0].endswith("gmt3_stress"))], pool)
    (output/"results.partial.json").replace(output/"report.json")
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--reference", type=Path, default=Path("reports/usdchf_direction_agent/report.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/usdchf_agent_improvement"))
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("Positive worker count required")
    run(args.history, args.reference, args.output, args.workers)
