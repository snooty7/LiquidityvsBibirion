"""Offline, cost-aware USDCHF direction/exit tests and causal monthly advisers."""
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
from src.strategy.cost_aware_agent import ClosedOutcome, fit_month, month_start
from src.tools import backtest_mt5 as replay
from src.tools.research_financing_resilience import task as reference_task, worker as reference_worker, normalize
from src.tools.research_swap_2k import initialize
from src.tools.research_usdchf_m30 import _forbid_broker
from src.tools.research_usdchf_risk05 import WINDOWS, settings
from src.tools.research_usdchf_three_ideas import register
from src.tools.walk_forward import RISK_KEYS, default_config_paths, discover_branches

VARIANTS = {
    "baseline": "Old M30/M1,1.5R activation/1R trailing gap; SELL flat only before triple swap",
    "buy_only": "Same baseline but BUY signals only; positive assumed BUY financing",
    "sell_only": "Same baseline but SELL signals only; pre-triple SELL exit retained",
    "fixed_2r": "Same baseline entries/initial risk; fixed2R TP, trailing off",
    "agent_positive": "Monthly gate: allow each side with >=8 closed shadow trades in preceding180days and positive mean stressed netR; otherwise cash",
    "agent_best": "Same monthly training, allow only highest positive mean stressed netR side; ties BUY; otherwise cash",
}
NEW_SOURCES = {"src/strategy/cost_aware_agent.py", "src/tools/research_direction_agent.py"}


def task(variant, offset, phase, stress, app, cfg, swaps, outcomes=()):
    """Construct a historical replay with unchanged risk/session/spread protections."""
    job = list(reference_task("triple_exit", offset, phase, stress, app, cfg, swaps))
    job[0] = f"{variant}_gmt{offset}"+("_stress" if stress else "")
    if variant in {"buy_only", "sell_only"}:
        job[3] = replace(cfg, trade_side_filter="buy" if variant == "buy_only" else "sell")
    elif variant == "fixed_2r":
        job[3] = replace(cfg, trailing_stop_mode="off")
    elif variant not in VARIANTS:
        raise ValueError("Unknown hypothesis")
    job[2] = replace(app, symbols=(job[3],))
    return tuple(job), variant, outcomes


@contextmanager
def adviser_gate(outcomes, best_only):
    """Wrap only simulated entry construction; restore it even on replay failure."""
    original = replay._build_entry_trade
    months, decisions = {}, []
    def build(cfg, runtime, info, equity, side, timestamp, *args, **kwargs):
        boundary = month_start(timestamp)
        if boundary not in months:
            months[boundary] = fit_month(outcomes, timestamp, best_only=best_only)
        advice = months[boundary]
        allow = side in advice.allowed_sides
        decisions.append({"time": timestamp, "side": side, "allow": allow, "fitted_at": boundary})
        if not allow:
            return None
        return original(cfg, runtime, info, equity, side, timestamp, *args, **kwargs)
    try:
        replay._build_entry_trade = build
        yield months, decisions
    finally:
        replay._build_entry_trade = original


def worker(item):
    """Replay genuine capacity/cost paths, never delete losing trades afterwards."""
    job, variant, outcomes = item
    if variant.startswith("agent_"):
        with adviser_gate(outcomes, variant == "agent_best") as (months, decisions):
            result = reference_worker(job)
        result["agent_months"] = [asdict(months[m]) for m in sorted(months)]
        result["agent_decisions"] = decisions
        for trade in result["trades"]:
            timestamp = int(datetime.fromisoformat(trade["entry_time_utc"]).timestamp())
            if trade["side"] not in months[month_start(timestamp)].allowed_sides:
                raise ValueError("Agent entered a forbidden side")
    else:
        result = reference_worker(job)
    return result


def nominate(records):
    """Rank only earlier GMT+3 stressed net; include reference and cash benchmark."""
    scores = {v: records[v+"_gmt3_stress"]["earlier"]["metrics"]["net_pnl"] for v in VARIANTS}
    ranking = sorted(scores, key=lambda v: (-scores[v],
        records[v+"_gmt3_stress"]["earlier"]["account"]["m1_close_drawdown"], v))
    return (ranking[0] if scores[ranking[0]] > 0 else "cash"), ranking


def run(history_path, reference_path, output, workers=6):
    """Freeze five ideas before outcomes and forbid all terminal/order operations."""
    _forbid_broker()
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    old = reference["plan"]
    history = load_history(history_path)["USDCHF"]
    source = next(b for b in discover_branches(default_config_paths()) if b.branch_id == "92024-USDCHF-M30-3c27c3d9")
    app, cfg, _ = settings(source, history.symbol_info)
    files = sorted(Path("src").rglob("*.py"))
    prior_digest = hashlib.sha256(b"".join(p.read_bytes() for p in files if p.as_posix() not in NEW_SOURCES)).hexdigest()
    if (prior_digest != old["code_digest"] or history.digest() != old["history_digest"]
        or normalize(asdict(cfg)) != old["settings"]
        or normalize({k: getattr(app.runtime, k) for k in RISK_KEYS}) != old["runtime"]):
        raise ValueError("Reference source/history/risk changed: cannot reuse controls")
    swaps = SwapModel(**{**old["swaps"], "weekday_weights": tuple(old["swaps"]["weekday_weights"])})
    training = {}
    for offset in (3, 2):
        trades = reference["results"][f"triple_exit_gmt{offset}_stress"]["full"]["trades"]
        training[offset] = tuple(ClosedOutcome(int(datetime.fromisoformat(t["exit_time_utc"]).timestamp()),
            t["side"], t["pnl_money"]/calc_position_risk_money(t["entry_price"], t["sl_initial"], t["volume"], history.symbol_info)) for t in trades)
    plan = {**{k: v for k, v in old.items() if k not in {"variants", "selection", "control_reuse", "code_digest", "success_diagnostics"}},
        "registered_at_utc": datetime.now(timezone.utc).isoformat(), "group": "direction_and_monthly_agent",
        "variants": VARIANTS, "reference_report_digest": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
        "code_digest": hashlib.sha256(b"".join(p.read_bytes() for p in files)).hexdigest(),
        "control_reuse": "12 triple-exit accounts copied exactly after original-source/history/config checks; only scenario labels renamed",
        "selection": "Earlier GMT+3 stressed net only, highest positive versus cash0; ties lower drawdown then name; lock before later/full new hypotheses. Rank all later/full results descriptively; no promotion from those reused dates.",
        "agent_protocol": "UTC monthly refit, preceding180 calendar days, shadow triple-exit reference trades EXITED strictly before month start, >=8 per side, positive mean net/initial cash price risk. Stressed reference outcomes train BOTH normal/stressed agent replays; clock-specific financing. No current-month exit labels, open trade outcomes, future prices or ongoing agent PnL used. Cold-start sides remain off. Initial history only begins at first reference entry; no invented warmup. Existing positions keep original exits when advice changes.",
        "agent_limits": "Deterministic adviser without execution dependencies. Simulated entry gate only; does not generate new market signals or claim general AI knowledge/guaranteed returns. Agent can reduce opportunity and overfit; shadow strategy is fixed based on reused historical research.",
        "risk_unchanged": "EUR10k,0.5% initial price risk,current equity sizing,maxlot0.5,one position,20pipSL,spread0.9,sessions,cooldown,dailyEUR150 and loss guards unchanged. Only direction gate or fixed2R exit differs. No stop widening or volume increase."}
    register(plan, output)
    records = {}
    for offset in (3, 2):
        for stress in (False, True):
            suffix = f"gmt{offset}"+("_stress" if stress else "")
            records["baseline_"+suffix] = normalize(reference["results"]["triple_exit_"+suffix])
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
            "basis": "Earlier GMT+3 stressed only; cash0 included"}, indent=2), encoding="utf-8")
        print("LOCKED", selected, flush=True)
        execute([j for j in jobs if not (j[0][1] == "earlier" and j[0][0].endswith("gmt3_stress"))], pool)
    (output/"results.partial.json").replace(output/"report.json")
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--reference", type=Path, default=Path("reports/usdchf_risk05_cost_resilience/report.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/usdchf_direction_agent"))
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("Positive worker count required")
    run(args.history, args.reference, args.output, args.workers)
