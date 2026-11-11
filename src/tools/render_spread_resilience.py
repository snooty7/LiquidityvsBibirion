"""Reconstruct and present every result in the frozen spread-resilience study."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import load_history
from src.risk.sizing import calc_position_risk_money
from src.tools.backtest_mt5 import ClosedTrade
from src.tools.research_capital_20k import outcomes
from src.tools.research_loss_reduction import account_curve
from src.tools.research_spread_resilience import code_hash, nominate


def assert_equal(expected, actual):
    if isinstance(expected, dict):
        if expected.keys() != actual.keys():
            raise ValueError("Report metric keys differ")
        for k in expected:
            assert_equal(expected[k], actual[k])
    elif isinstance(expected, (float, int)):
        if not math.isclose(expected, actual, rel_tol=1e-10, abs_tol=1e-8):
            raise ValueError("Recomputed metric differs")
    elif expected != actual:
        raise ValueError("Recomputed metric differs")


def audit(report, history):
    """Validate stored fills independently of the replay worker and reconstruct continuous equity."""
    plan = report["plan"]
    if plan["replay_code_sha256"] != code_hash() or plan["history_sha256"] != history.digest():
        raise ValueError("Code/history fingerprint differs from registration")
    if plan["costs"] != asdict(ExecutionCosts()) or plan["stress_costs"] != asdict(ExecutionCosts("historical", 2, 7, .4)):
        raise ValueError("Registered normal/doubled costs changed")
    runtime = plan["risk_runtime"]
    if (runtime["daily_loss_limit_usd"] != 150 or runtime["max_total_open_risk_pct"] != .5
            or not runtime["close_positions_on_daily_loss"] or runtime["per_trade_loss_guard_mode"] != "position_risk"
            or runtime["per_trade_loss_risk_multiple"] != 1):
        raise ValueError("A runtime risk protection changed")
    expected_names = set(plan["settings"])
    if set(report["comparison"]) != expected_names:
        raise ValueError("Candidate set differs")
    baseline = plan["settings"]["baseline"]
    allowed = {"baseline": set(), "trail_later_1_5": {"trailing_activation_r"},
        "trail_gap_1_25": {"trailing_gap_r"}, "stronger_confirmation": {"confirmation_displacement_range_multiple"},
        "fresh_confirmation": {"confirm_expiry_bars"}}
    if expected_names != set(allowed):
        raise ValueError("Unexpected hypothesis")
    for name, cfg in plan["settings"].items():
        if {k for k, v in cfg.items() if v != baseline[k]} != allowed[name]:
            raise ValueError("Candidate changed an undeclared parameter")
        if cfg["risk_pct"] != .5 or cfg["max_lot"] != .5 or cfg["max_spread_pips"] != .9:
            raise ValueError("Fixed risk or spread setting changed")
    expected_phases = {"earlier", "earlier_stress", "later", "later_stress", "full", "full_stress"}
    trade_count = 0
    for name, phases in report["comparison"].items():
        if set(phases) != expected_phases:
            raise ValueError("Missing or unexpected replay")
        for phase, row in phases.items():
            if row["name"] != name or row["phase"] != phase:
                raise ValueError("Replay identity mismatch")
            window = plan["windows"][phase.removesuffix("_stress")]
            if row["start"] != window["start"] or row["end_exclusive"] != window["end_exclusive"]:
                raise ValueError("Replay boundaries differ from registration")
            costs = ExecutionCosts(**plan["stress_costs" if phase.endswith("_stress") else "costs"])
            trades = [ClosedTrade(**t) for t in row["trades"]]
            assert_equal({k: row[k] for k in outcomes(trades)}, outcomes(trades))
            assert_equal(row["account"], account_curve(trades, history, costs))
            cash, prior_exit = 20000., ""
            for t in trades:
                if not row["start"] <= t.entry_time_utc < row["end_exclusive"] or not (
                        t.entry_time_utc <= t.exit_time_utc <= row["end_exclusive"]):
                    raise ValueError("Out-of-window trade")
                if t.entry_time_utc < prior_exit:
                    raise ValueError("Overlapping positions")
                risk = calc_position_risk_money(t.entry_price, t.sl_initial, t.volume, history.symbol_info)
                if risk > cash*.005+1e-7 or not 0 < t.volume <= .5:
                    raise ValueError("Unchanged sizing limits violated")
                if (t.side == "BUY" and t.exit_sl < t.sl_initial) or (t.side == "SELL" and t.exit_sl > t.sl_initial):
                    raise ValueError("Protective stop widened")
                if not math.isclose(t.commission_cost_money, 2*t.volume*costs.commission_per_lot, abs_tol=1e-8):
                    raise ValueError("Commission differs")
                if not math.isclose(t.gross_pnl_money-t.spread_cost_money-t.commission_cost_money-t.slippage_cost_money,
                                    t.pnl_money, abs_tol=1e-8):
                    raise ValueError("Costs do not reconcile")
                cash += t.pnl_money
                prior_exit = t.exit_time_utc
                trade_count += 1
            if not math.isclose(cash, row["account"]["end_equity"], abs_tol=1e-7):
                raise ValueError("Continuous final balance differs")
    selected, ranking = nominate({n: p["earlier_stress"] for n, p in report["comparison"].items()})
    if report["locked_selection"] != {"selected": selected, "earlier_stress_ranking": ranking}:
        raise ValueError("Earlier-only nomination differs")
    checks = {}
    for name, phases in report["comparison"].items():
        checks[name] = {"full_base_profitable": phases["full"]["metrics"]["net_pnl"] > 0,
            "full_stress_profitable": phases["full_stress"]["metrics"]["net_pnl"] > 0,
            "later_stress_profitable": phases["later_stress"]["metrics"]["net_pnl"] > 0,
            "winning_trade_goal": all(100 <= phases[p]["mean_winner"] <= 200 and phases[p]["wins_100_to_200"] > 0
                                      for p in ("full", "full_stress", "later_stress"))}
    assert_equal(report["descriptive_checks"], checks)
    if report["nominee_meets_historical_objective"] != all(checks[selected].values()):
        raise ValueError("Historical success claim differs from actual results")
    return {"passed": True, "continuous_replays": 30, "simulated_trade_records_checked": trade_count,
            "checks": ["frozen code/history", "all five hypotheses and six scenarios", "only declared parameter changes",
                "every profit/target statistic reconstructed", "M1 floating equity and final balances reconstructed",
                "0.5% sizing budget and unchanged lot cap", "no widened stops", "cost reconciliation",
                "trade boundaries and single position", "earlier-stress-only nomination"], "live_settings_changed": False}


def render(report):
    comparison = report["comparison"]
    selected = report["locked_selection"]["selected"]
    ranking = sorted(comparison, key=lambda n: (-comparison[n]["full_stress"]["metrics"]["net_pnl"], n))
    lines = ["# USDCHF spread <=0.9: cost-resilience improvement", "",
        f'**Earlier-stress nominee: `{selected}`. Meets declared descriptive objective: {report["nominee_meets_historical_objective"]}.**', "",
        "EUR20,000 starting capital, 0.5% risk per entry. One continuous account per scenario, no monthly resets. "
        "Full period: 15 November 2024 through 10 November 2026 UTC. **Swap/financing is excluded.**", "",
        "## Full account: normal and doubled costs", "",
        "| Model | Normal end EUR | Normal net EUR | Doubled-cost end EUR | Doubled-cost net EUR | Stressed equity DD EUR | Stressed mean winner EUR | EUR100-200 winners | Trades |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name in ranking:
        normal, stress = comparison[name]["full"], comparison[name]["full_stress"]
        lines.append(f'| {name} | {normal["account"]["end_equity"]:.2f} | {normal["metrics"]["net_pnl"]:.2f} | '
            f'{stress["account"]["end_equity"]:.2f} | {stress["metrics"]["net_pnl"]:.2f} | '
            f'{stress["account"]["m1_close_drawdown"]:.2f} | {stress["mean_winner"]:.2f} | '
            f'{stress["wins_100_to_200"]} | {stress["metrics"]["trades"]} |')
    lines += ["", "## Separate continuous periods under doubled costs", "",
        "Each period starts with EUR20,000 independently. These balances are not added into a single account. "
        "The earlier period alone chooses the fixed nominee; full-history rankings above are descriptive.", "",
        "| Model | Earlier net EUR | Earlier equity DD EUR | Later net EUR | Later equity DD EUR | Later mean winner EUR |",
        "|---|---:|---:|---:|---:|---:|"]
    for name in ranking:
        early, later = comparison[name]["earlier_stress"], comparison[name]["later_stress"]
        lines.append(f'| {name} | {early["metrics"]["net_pnl"]:.2f} | {early["account"]["m1_close_drawdown"]:.2f} | '
            f'{later["metrics"]["net_pnl"]:.2f} | {later["account"]["m1_close_drawdown"]:.2f} | '
            f'{later["mean_winner"]:.2f} |')
    lines += ["", "## Winning trades versus all trades: full doubled-cost account", "",
        "| Model | Mean winner EUR | Mean loser EUR | Mean all EUR | Largest loss EUR | Winners | EUR100-200 winners | Winners above EUR200 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name in ranking:
        r = comparison[name]["full_stress"]
        lines.append(f'| {name} | {r["mean_winner"]:.2f} | {r["mean_loser"]:.2f} | {r["mean_all"]:.2f} | '
            f'{r["largest_loss"]:.2f} | {r["wins"]} | {r["wins_100_to_200"]} | {r["wins_above_200"]} |')
    lines += ["", "## Fixed hypotheses and accounting", ""]
    lines += [f'- `{n}`: {note}' for n, note in report["plan"]["hypotheses"].items()]
    lines += ["- " + report["plan"]["fixed"], "- " + report["plan"]["selection"],
              "- " + report["plan"]["accounting"],
              "- Success criterion: " + report["plan"]["success_measure"],
              "- Normal costs are historical spread, EUR3.50/lot/side commission and 0.2-pip adverse market/stop slippage."]
    lines += ["- " + s for s in report["plan"]["limitations"]]
    lines += ["- No active settings changed. Broker initialization and order methods are blocked during offline replay. No bot started or real orders placed.",
        "", "## Reproduce and audit", "", "```powershell", "python -m src.tools.research_spread_resilience --workers 4",
        "python -m src.tools.render_spread_resilience reports/usdchf_spread_resilience/report.json", "```", "",
        "plan.json records frozen hypotheses, settings and code/data hashes; locked_selection.json records "
        "the older-stress choice before later/full outcomes. report.json retains all 30 replays and actual "
        "simulated trades. audit.json independently reconstructs their account paths and cost/goal metrics.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--history", type=Path, default=Path("history/mt5_20261111/USDCHF_extended.json"))
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    history = load_history(args.history)["USDCHF"]
    result = audit(report, history)
    args.report.with_name("audit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    args.report.with_name("README.md").write_text(render(report), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
