"""Offline configurable-capital / 0.75% replay of the fixed USDCHF 1.5R candidate."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import load_history
from src.backtesting.swaps import SwapModel, rates_from_snapshot, weekday_weights
from src.risk.sizing import calc_position_risk_money
from src.tools.backtest_mt5 import run_backtest
from src.tools.research_capital_20k import outcomes
from src.tools.research_loss_reduction import account_curve
from src.tools.research_spread_resilience import configurations
from src.tools.research_usdchf_m30 import _forbid_broker, study_folds
from src.tools.research_usdchf_three_ideas import register
from src.tools.walk_forward import RISK_KEYS, default_config_paths, discover_branches, history_coverage

CAPITAL = 2000.0
_history = None


def initialize(path):
    """Load local history and make broker operations fail closed in each worker."""
    global _history
    _forbid_broker()
    _history = load_history(Path(path))["USDCHF"]


def worker(task):
    """Replay one independent continuous account and reconcile risk and cash flows."""
    if len(task) not in (9, 10):
        raise ValueError("Expected replay task with optional overnight policy")
    name, phase, app, cfg, start, end, costs, swaps, capital = task[:9]
    overnight_policy = task[9] if len(task) == 10 else None
    reason = history_coverage(_history, cfg, start, end, max_gap_days=4)
    if reason:
        raise ValueError(reason)
    result, trades = run_backtest(app, cfg, start, end, initial_equity=capital,
                                 costs=costs, swaps=swaps, history=_history, end_exclusive=True,
                                 overnight_policy=overnight_policy)
    cash = capital
    for trade in trades:
        risk = calc_position_risk_money(trade.entry_price, trade.sl_initial, trade.volume, _history.symbol_info)
        if risk > cash * cfg.risk_pct / 100 + 1e-7 or trade.volume > cfg.max_lot + 1e-9:
            raise ValueError("Risk budget exceeded")
        expected = (trade.gross_pnl_money - trade.spread_cost_money - trade.commission_cost_money
                    - trade.slippage_cost_money + trade.swap_money)
        if not math.isclose(expected, trade.pnl_money, abs_tol=1e-8):
            raise ValueError("Cost accounting does not reconcile")
        cash += trade.pnl_money
    account = account_curve(trades, _history, costs, initial_equity=capital)
    if not math.isclose(result.ending_equity, cash, abs_tol=1e-7):
        raise ValueError("Replay and trade-ledger balances disagree")
    if not math.isclose(account["end_equity"], cash, abs_tol=1e-7):
        raise ValueError("Equity curve and ledger disagree")
    return {"scenario": name, "window": phase, **outcomes(trades, capital), "account": account,
            "swap_net": sum(t.swap_money for t in trades),
            "swap_debits": sum(min(0, amount) for t in trades for _, amount in t.swap_events),
            "swap_credits": sum(max(0, amount) for t in trades for _, amount in t.swap_events),
            "trades": [asdict(t) for t in trades]}


def run(history_path, snapshot_path, output, workers=3, baseline_only=False, capital=CAPITAL,
        triple_day_override=None):
    """Freeze all assumptions before reading scenario outcomes; no parameter search."""
    if not math.isfinite(capital) or capital <= 0:
        raise ValueError("Starting capital must be finite and positive")
    _forbid_broker()
    history = load_history(history_path)["USDCHF"]
    source = next(b for b in discover_branches(default_config_paths())
                  if b.branch_id == "92024-USDCHF-M30-3c27c3d9")
    cfg = replace(configurations(source.symbol)["trail_later_1_5"], risk_pct=.75)
    # The previous 0.5% aggregate cap would reject every requested 0.75% entry.
    app = replace(source.config, runtime=replace(source.config.runtime, max_total_open_risk_pct=.75))
    folds = study_folds(365)
    windows = {"earlier": (folds[0].train_start, folds[0].train_end),
               "later": (folds[0].test_start, folds[-1].test_end),
               "full": (folds[0].train_start, folds[-1].test_end)}
    scenarios = {"no_swap": (ExecutionCosts(), None),
                 "no_swap_stress": (ExecutionCosts("historical", 2, 7, .4), None)}
    snapshot = None
    if not baseline_only:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        symbol = next(s for s in snapshot["symbols"] if s["name"].rstrip("-") == "USDCHF")
        buy, sell = rates_from_snapshot(symbol, history.symbol_info, snapshot["account_currency"])
        weights = weekday_weights(symbol, triple_day_override)
        for offset in (3, 2):
            for stress in (False, True):
                name = f"swap_gmt{offset}" + ("_stress" if stress else "")
                scenarios[name] = (ExecutionCosts("historical", 2, 7, .4) if stress else ExecutionCosts(),
                    SwapModel(buy, sell, f"Etc/GMT-{offset}", tuple(weights), 2 if stress else 1))
    files = sorted(Path("src").rglob("*.py"))
    plan = {"capital": capital, "risk_pct": .75, "settings": asdict(cfg),
            "runtime": {key: getattr(app.runtime, key) for key in RISK_KEYS},
            "windows": {n: [a.isoformat(), b.isoformat()] for n, (a, b) in windows.items()},
            "scenarios": {n: {"costs": asdict(c), "swaps": asdict(s) if s else None} for n, (c, s) in scenarios.items()},
            "swap_snapshot": snapshot, "triple_day_override": triple_day_override,
            "history_digest": history.digest(),
            "code_digest": hashlib.sha256(b"".join(p.read_bytes() for p in files)).hexdigest(),
            "limitations": ["Reused historical dates; no untouched holdout or new strategy selection.",
                "Current swap snapshot held constant over history; actual historical daily swap rates unavailable.",
                "Broker midnight GMT+3 assumed, GMT+2 sensitivity; historical clock policy not established.",
                "Observed spreads unchanged in stress; commission/slippage and negative swap debits doubled, credits unchanged.",
                "Constant EUR tick valuation; margin, latency and tick extrema not reconstructed.",
                "Swap booked before bar-open risk checks; entry at rollover exempt, exit at rollover before next bar exempt. Minute granularity.",
                "EUR150 daily guard retained; paper aggregate exposure cap aligned to requested 0.75% per entry. Live config unchanged.",
                "EUR100-200 winning-trade target is measured, never forced by increasing volume."],
            "broker_operations": False, "live_config_changed": False}
    output.mkdir(parents=True, exist_ok=True)
    register(plan, output)
    records = {}
    with ProcessPoolExecutor(max_workers=workers, initializer=initialize, initargs=(str(history_path),)) as pool:
        jobs = [pool.submit(worker, (name, phase, app, cfg, start, end, costs, swaps, capital))
                for name, (costs, swaps) in scenarios.items() for phase, (start, end) in windows.items()]
        for future in as_completed(jobs):
            record = future.result()
            records.setdefault(record["scenario"], {})[record["window"]] = record
            print(record["scenario"], record["window"], round(record["metrics"]["net_pnl"], 2), flush=True)
    (output/"report.json").write_text(json.dumps({"plan": plan, "results": records}, indent=2, allow_nan=False), encoding="utf-8")
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--capital", type=float, default=CAPITAL)
    parser.add_argument("--triple-day", type=int, choices=range(7),
                        help="Explicit documented weekday override (Sunday=0); recorded in plan")
    parser.add_argument("--baseline-only", action="store_true")
    args = parser.parse_args()
    if args.workers < 1 or not math.isfinite(args.capital) or args.capital <= 0 or (not args.baseline_only and args.snapshot is None):
        parser.error("Positive workers and a swap snapshot required (unless baseline-only)")
    run(args.history, args.snapshot, args.output, args.workers, args.baseline_only, args.capital, args.triple_day)
