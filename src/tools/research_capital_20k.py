"""Offline EUR20k sizing illustration; no active settings, broker access or trades."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import load_history
from src.risk.sizing import calc_position_risk_money
from src.tools import backtest_mt5 as replay
from src.tools.research_usdchf_m30 import _forbid_broker, study_folds
from src.tools.research_usdchf_three_ideas import register, source_hash
from src.tools.walk_forward import RISK_KEYS, default_config_paths, discover_branches, history_coverage, trade_metrics

CAPITAL = 20000.
RISKS = (.1, .2, .3, .5)
PAPER_LOT_CAP = .5
_history = None


def outcomes(trades, initial_equity=CAPITAL):
    """Separate a winning trade from the average result including losing trades."""
    wins = [t.pnl_money for t in trades if t.pnl_money > 0]
    losses = [t.pnl_money for t in trades if t.pnl_money < 0]
    return {"metrics": trade_metrics(trades, initial_equity),
            "mean_winner": statistics.mean(wins) if wins else 0,
            "mean_loser": statistics.mean(losses) if losses else 0,
            "mean_all": statistics.mean(t.pnl_money for t in trades) if trades else 0,
            "largest_win": max(wins, default=0), "largest_loss": min(losses, default=0),
            "wins": len(wins), "wins_100_to_200": sum(100 <= p <= 200 for p in wins),
            "wins_at_least_100": sum(p >= 100 for p in wins), "wins_above_200": sum(p > 200 for p in wins),
            "volumes": dict(sorted(Counter(f"{t.volume:g}" for t in trades).items()))}


def code_hash():
    return hashlib.sha256(source_hash().encode()+Path(__file__).read_bytes()).hexdigest()


def initialize(path):
    global _history
    _forbid_broker()
    _history = load_history(Path(path))["USDCHF"]


def worker(task):
    app, cfg, start, end, costs, phase, fold = task
    reason = history_coverage(_history, cfg, start, end, max_gap_days=4)
    if reason:
        raise ValueError(reason)
    _, trades = replay.run_backtest(app, cfg, start, end, initial_equity=CAPITAL, costs=costs,
                                    history=_history, end_exclusive=True)
    equity = CAPITAL
    for t in trades:
        if not start <= datetime.fromisoformat(t.entry_time_utc) < end or not (
                datetime.fromisoformat(t.entry_time_utc) <= datetime.fromisoformat(t.exit_time_utc) <= end):
            raise ValueError("Out-of-window trade")
        risk = calc_position_risk_money(t.entry_price, t.sl_initial, t.volume, _history.symbol_info)
        if risk > equity*cfg.risk_pct/100+1e-7 or t.volume > PAPER_LOT_CAP+1e-9:
            raise ValueError("Paper trade exceeded sizing budget")
        if not math.isclose(t.gross_pnl_money-t.spread_cost_money-t.commission_cost_money-t.slippage_cost_money,
                            t.pnl_money, abs_tol=1e-8):
            raise ValueError("Costs do not reconcile")
        equity += t.pnl_money
    return {"risk_pct": cfg.risk_pct, "phase": phase, "fold": fold,
            "start": start.isoformat(), "end_exclusive": end.isoformat(),
            **outcomes(trades), "trades": [asdict(t) for t in trades]}


def run(path, output, workers=4, register_only=False):
    _forbid_broker()
    source = next(b for b in discover_branches(default_config_paths()) if b.branch_id == "92024-USDCHF-M30-3c27c3d9")
    cfgs = {r: replace(source.symbol, cisd_timeframe="M1", cisd_lookback_bars=300,
                        risk_pct=r, max_lot=PAPER_LOT_CAP) for r in RISKS}
    history = load_history(path)["USDCHF"]
    folds = study_folds(365)
    costs, stress = ExecutionCosts(), ExecutionCosts("historical", 2, 7, .4)
    plan = {"registered_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Measure whether successful simulated trades reach EUR100-200, separately from average after losses",
        "capital_per_replay": CAPITAL, "risk_levels_pct": list(RISKS), "paper_max_lot": PAPER_LOT_CAP,
        "settings": {str(r): asdict(c) for r, c in cfgs.items()},
        "risk_runtime": {k: getattr(source.config.runtime, k) for k in RISK_KEYS},
        "changed_only_in_simulation": "Starting equity EUR20,000; max lot ceiling raised from 0.05 to 0.5; declared risk 0.1/0.2/0.3/0.5%. No live settings changed.",
        "unchanged": "Same USDCHF M30/M1 signals, stop, target, trailing, sessions, cooldown, one-position rule, EUR150 daily guard and 0.5% portfolio exposure guard. Position size remains risk-derived; no loss chasing or stop widening.",
        "costs": asdict(costs), "stress_costs": asdict(stress),
        "history_sha256": history.digest(), "replay_code_sha256": code_hash(),
        "folds": [f.record() for f in folds],
        "earlier_year": {"start": folds[0].train_start.isoformat(), "end_exclusive": folds[0].train_end.isoformat()},
        "limitations": ["Previously examined history, not untouched evidence or a guarantee of future profits.",
            "Monthly tests reset flat at EUR20,000; no continuous compounding. Realized drawdown omits intratrade equity fluctuations.",
            "Historical spreads; assumed commission/slippage and constant valuation. Swap/overnight financing and full tick/latency effects excluded.",
            "EUR150 daily guard is a trigger, not a guaranteed maximum day loss; fills and gaps can exceed it.",
            "Profit from a successful trade does not mean profit from every trade or positive long-term expectancy. Earlier losing-year and cost-stress results are retained."],
        "broker_connections": False, "trading_calls": False, "live_settings_changed": False}
    del history
    plan = register(plan, output)
    if register_only:
        print("Registered EUR20k PAPER study; higher volume ceiling is simulation-only", flush=True)
        return plan
    tasks = []
    for risk, cfg in cfgs.items():
        tasks += [(source.config, cfg, f.train_start, f.train_end, scenario, phase, 0)
                  for f in folds[:1] for scenario, phase in ((costs, "earlier"), (stress, "earlier_stress"))]
        tasks += [(source.config, cfg, f.test_start, f.test_end, costs, "base", f.index) for f in folds]
        tasks += [(source.config, cfg, f.test_start, f.test_end, stress, "stress", f.index) for f in folds[6:]]
    rows = []
    with ProcessPoolExecutor(max_workers=workers, initializer=initialize, initargs=(str(path),)) as pool:
        futures = [pool.submit(worker, task) for task in tasks]
        for index, future in enumerate(as_completed(futures), 1):
            rows.append(future.result())
            print(f"replay {index}/{len(futures)}", flush=True)
    rows.sort(key=lambda r: (r["risk_pct"], r["phase"], r["fold"]))
    comparison = {}
    for risk in RISKS:
        comparison[str(risk)] = {}
        for scope, phase, indices in (("test_year", "base", set(range(1, 13))),
            ("confirmation", "base", set(range(7, 13))), ("stress_confirmation", "stress", set(range(7, 13))),
            ("earlier_year", "earlier", {0}), ("earlier_year_stress", "earlier_stress", {0})):
            trades = [replay.ClosedTrade(**t) for row in rows if row["risk_pct"] == risk
                      and row["phase"] == phase and row["fold"] in indices for t in row["trades"]]
            comparison[str(risk)][scope] = outcomes(trades)
    report = {"plan": plan, "comparison": comparison, "rows": rows}
    (output/"report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    lines = ["# EUR20k USDCHF paper sizing: EUR100-200 successful trades", "",
        "**Simulation only. No live risk/capital/lot setting changed.**", "",
        "| Risk budget | Mean winner EUR | Mean loser EUR | Mean all EUR | Wins EUR100-200 | Total trades | Year net EUR | Realized DD EUR | Earlier-year net EUR |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for risk, scopes in comparison.items():
        r = scopes["test_year"]
        lines.append(f'| {risk}% | {r["mean_winner"]:.2f} | {r["mean_loser"]:.2f} | {r["mean_all"]:.2f} | '
            f'{r["wins_100_to_200"]} | {r["metrics"]["trades"]} | {r["metrics"]["net_pnl"]:.2f} | '
            f'{r["metrics"]["max_realized_drawdown"]:.2f} | {scopes["earlier_year"]["metrics"]["net_pnl"]:.2f} |')
    lines += ["", plan["changed_only_in_simulation"], "", plan["unchanged"], "",
        "Twelve monthly tests: 16 November 2025 to 11 November 2026 exclusive. Earlier year: "
        "15 November 2024 to 15 November 2025 exclusive. Every replay starts at EUR20,000. "
        "Base costs: observed spread, EUR3.50/lot/side commission, 0.2-pip adverse market/stop slippage. "
        "Earlier year and later six tests are also replayed with EUR7.00 commission and 0.4-pip slippage; "
        "observed spreads unchanged, missing-spread fallback doubled. Detailed distributions, extreme "
        "wins/losses and cost-stress results are retained in report.json.", ""]
    lines += ["- "+note for note in plan["limitations"]]
    lines += ["- No bot started, broker connected or orders placed.", "",
              "Reproduce: `python -m src.tools.research_capital_20k`", ""]
    (output/"README.md").write_text("\n".join(lines), encoding="utf-8")
    print("FINISHED", json.dumps(comparison), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, default=Path("history/mt5_20261111/USDCHF_extended.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/usdchf_capital_20k"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--register-only", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("workers must be positive")
    run(args.history, args.output, args.workers, args.register_only)


if __name__ == "__main__":
    main()
