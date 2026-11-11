"""One offline experiment: legacy same-side/same-level re-entry protection, risk unchanged."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import load_history
from src.tools import backtest_mt5 as replay
from src.tools.research_usdchf_m30 import _forbid_broker, study_folds
from src.tools.research_usdchf_three_ideas import register, source_hash
from src.tools.walk_forward import RISK_KEYS, default_config_paths, discover_branches, history_coverage, trade_metrics

_history = None
LOCK_BARS = 2
LEVEL_PIPS = 6.0


def locked(previous: dict | None, side: str, level: float, candle_time: int, pip: float) -> bool:
    """Replicate the legacy rule: two M30 setup bars, same direction, <=6 pips apart."""
    if previous is None or previous["side"] != side:
        return False
    if candle_time > previous["time"]+LOCK_BARS*1800:
        return False
    return abs(level-previous["level"])/pip <= LEVEL_PIPS+1e-9


@contextmanager
def paper_entry_gate(enabled: bool):
    """Intercept only simulated entries; never import or execute the legacy bot.

    A process-local research hook avoids installing an unvalidated feature in live
    settings. State changes only after successful paper sizing, never rejected orders.
    """
    original = replay._build_entry_trade
    state = {"previous": None, "blocked": 0}
    def build(cfg, runtime, info, equity, side, timestamp, price, key, note, pending=None, **kwargs):
        if enabled and pending is not None and locked(state["previous"], side, float(pending.level),
                                                      int(pending.candle_time), replay.MT5Adapter.pip_size(info)):
            state["blocked"] += 1
            return None
        trade = original(cfg, runtime, info, equity, side, timestamp, price, key, note, pending, **kwargs)
        if trade is not None and pending is not None:
            state["previous"] = {"side": side, "level": float(pending.level), "time": int(pending.candle_time)}
        return trade
    try:
        replay._build_entry_trade = build
        yield state
    finally:
        replay._build_entry_trade = original


def code_hash():
    return hashlib.sha256(source_hash().encode()+Path(__file__).read_bytes()).hexdigest()


def initialize(path):
    global _history
    _forbid_broker()
    _history = load_history(Path(path))["USDCHF"]


def worker(task):
    app, cfg, start, end, costs, enabled, fold, phase = task
    reason = history_coverage(_history, cfg, start, end, max_gap_days=4)
    if reason:
        raise ValueError(reason)
    with paper_entry_gate(enabled) as state:
        _, trades = replay.run_backtest(app, cfg, start, end, initial_equity=10000, costs=costs,
                                        history=_history, end_exclusive=True)
    for trade in trades:
        if not start <= datetime.fromisoformat(trade.entry_time_utc) < end or not (
                datetime.fromisoformat(trade.entry_time_utc) <= datetime.fromisoformat(trade.exit_time_utc) <= end):
            raise ValueError("Out-of-window trade")
    return {"model": "reentry" if enabled else "baseline", "fold": fold, "phase": phase,
            "start": start.isoformat(), "end_exclusive": end.isoformat(), "blocked": state["blocked"],
            "metrics": trade_metrics(trades, 10000), "trades": [asdict(t) for t in trades]}


def run(path, output, workers=4, register_only=False):
    _forbid_broker()
    source = next(b for b in discover_branches(default_config_paths()) if b.branch_id == "92024-USDCHF-M30-3c27c3d9")
    cfg = replace(source.symbol, cisd_timeframe="M1", cisd_lookback_bars=300)
    history = load_history(path)["USDCHF"]
    folds = study_folds(365)
    costs, stress = ExecutionCosts(), ExecutionCosts("historical", 2, 7, .4)
    plan = {"registered_at_utc": datetime.now(timezone.utc).isoformat(),
        "experiment": "One fixed legacy re-entry rule; no tuning or other strategy changes",
        "rule": "After a successful simulated entry, block a new entry in the same direction within 6 pips of its setup level when the new setup candle is <=2 M30 bars after the previous executed setup candle. Opposite direction passes. Existing one-hour cooldown stays unchanged.",
        "settings": asdict(cfg), "risk_runtime": {k: getattr(source.config.runtime, k) for k in RISK_KEYS},
        "history_sha256": history.digest(), "replay_code_sha256": code_hash(),
        "costs": asdict(costs), "stress_costs": asdict(stress), "folds": [f.record() for f in folds],
        "initial_equity_per_fold": 10000,
        "limitations": ["Previously examined dates; not untouched validation.",
            "Monthly windows reset flat; no compounding; realized drawdown excludes intratrade equity swings.",
            "Swap/overnight financing excluded; commission/slippage assumed and symbol valuation held constant.",
            "Research-only paper-entry hook; no live implementation or active setting change. Its blocked entries are counted separately from the generic replay risk-skip counter."],
        "broker_connections": False, "trading_calls": False}
    del history
    plan = register(plan, output)
    if register_only:
        print("Registered ONE re-entry rule, unchanged risk", flush=True)
        return plan
    tasks = []
    for enabled in (False, True):
        tasks += [(source.config, cfg, f.test_start, f.test_end, costs, enabled, f.index, "base") for f in folds]
        tasks += [(source.config, cfg, f.test_start, f.test_end, stress, enabled, f.index, "stress") for f in folds[6:]]
    rows = []
    with ProcessPoolExecutor(max_workers=workers, initializer=initialize, initargs=(str(path),)) as pool:
        futures = [pool.submit(worker, task) for task in tasks]
        for index, future in enumerate(as_completed(futures), 1):
            rows.append(future.result())
            print(f"replay {index}/{len(futures)}", flush=True)
    rows.sort(key=lambda r: (r["model"], r["phase"], r["fold"]))
    comparison = {}
    for model in ("baseline", "reentry"):
        comparison[model] = {}
        for scope, phase, indices in (("test_year", "base", set(range(1, 13))),
                ("confirmation", "base", set(range(7, 13))), ("stress_confirmation", "stress", set(range(7, 13)))):
            selected = [r for r in rows if r["model"] == model and r["phase"] == phase and r["fold"] in indices]
            trades = [replay.ClosedTrade(**t) for r in selected for t in r["trades"]]
            comparison[model][scope] = {"metrics": trade_metrics(trades, 10000), "blocked": sum(r["blocked"] for r in selected)}
    report = {"plan": plan, "comparison": comparison, "rows": rows, "live_settings_changed": False}
    (output/"report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    # Reconcile all saved costs independently before publishing the short result.
    for row in rows:
        for trade in row["trades"]:
            if not math.isclose(trade["gross_pnl_money"]-trade["spread_cost_money"]-trade["commission_cost_money"]
                                -trade["slippage_cost_money"], trade["pnl_money"], abs_tol=1e-8):
                raise ValueError("Trade costs do not reconcile")
    lines = ["# USDCHF M30/M1: one same-level re-entry test", "",
        "Virtual EUR 10,000 per monthly window. Risk 0.1%, max lot 0.05, same stops, trailing and daily/exposure guards.", "",
        "| Model | Net after modeled costs EUR | Max realized drawdown EUR | Blocked entries |",
        "|---|---:|---:|---:|"]
    for model in comparison:
        r = comparison[model]["test_year"]
        lines.append(f'| {model} | {r["metrics"]["net_pnl"]:.2f} | {r["metrics"]["max_realized_drawdown"]:.2f} | {r["blocked"]} |')
    lines += ["", "Rule: " + plan["rule"], "",
        "Twelve 30-day windows: 16 November 2025 to 11 November 2026 exclusive. Native saved history only. "
        "Historical spread, EUR 3.50/lot/side assumed commission, 0.2-pip adverse market/stop slippage. "
        "Later-six doubled commission/slippage results are in report.json.", ""]
    lines += ["- " + s for s in plan["limitations"]]
    lines += ["- No bot started, broker connected or orders sent. No live settings changed.", "",
        "Reproduce: `python -m src.tools.research_reentry`", ""]
    (output/"README.md").write_text("\n".join(lines), encoding="utf-8")
    print("FINISHED", json.dumps(comparison), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, default=Path("history/mt5_20261111/USDCHF_extended.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/usdchf_reentry"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--register-only", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("workers must be positive")
    run(args.history, args.output, args.workers, args.register_only)


if __name__ == "__main__":
    main()
