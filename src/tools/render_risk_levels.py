"""Audit and explain sizing sensitivity without changing live risk settings."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import json
import math
from pathlib import Path

from src.risk.sizing import SymbolTradeInfo
from src.services.config import SymbolConfig
from src.tools.backtest_mt5 import ClosedTrade
from src.tools.research_risk_levels import RISK_LEVELS, REFERENCES, loss_streaks, record_metrics
from src.tools.walk_forward import trade_metrics


def _equal(expected, actual):
    if isinstance(expected, dict):
        if expected.keys() != actual.keys():
            raise ValueError("Audit keys differ")
        for key in expected:
            _equal(expected[key], actual[key])
    elif isinstance(expected, (int, float)):
        if not math.isclose(expected, actual, rel_tol=1e-10, abs_tol=1e-8):
            raise ValueError("Recomputed audit value differs")
    elif expected != actual:
        raise ValueError("Recomputed audit value differs")


def audit(report: dict, raw_trades: list[dict]) -> dict:
    """Reconstruct all metrics and entry equity from saved fills, including earlier losses."""
    plan = report["plan"]
    settings = {name: SymbolConfig(**cfg) for name, cfg in plan["settings"].items()}
    expected_names = {f"{ref}_risk_{risk:g}" for ref in REFERENCES for risk in RISK_LEVELS}
    if set(settings) != expected_names:
        raise ValueError("Unexpected risk scenario")
    for reference in REFERENCES:
        baseline = asdict(settings[f"{reference}_risk_0.1"])
        for risk in RISK_LEVELS:
            cfg = asdict(settings[f"{reference}_risk_{risk:g}"])
            if {k for k, v in cfg.items() if v != baseline[k]} - {"risk_pct"}:
                raise ValueError("A protection changed within risk scenarios")
            if cfg["max_lot"] != .05 or cfg["sl_pips"] != 20 or cfg["ignore_portfolio_cap"]:
                raise ValueError("A fixed protection was relaxed")
    if plan["risk_runtime"]["daily_loss_limit_usd"] != 150 or plan["risk_runtime"]["max_total_open_risk_pct"] != .5:
        raise ValueError("Daily or portfolio cap was changed")
    expected = {(name, phase, i) for name in settings for phase, indices in (
        ("earlier_base", [0]), ("earlier_stress", [0]), ("test_base", range(1, 13)),
        ("test_stress", range(7, 13))) for i in indices}
    rows = report["rows"]
    keys = {(r["name"], r["phase"], r["fold"]) for r in rows}
    if keys != expected or len(rows) != len(expected) or report["unique_replays"] != len(expected):
        raise ValueError("Missing or duplicated risk replay")
    grouped = defaultdict(list)
    for raw in raw_trades:
        key = raw["name"], raw["phase"], raw["fold"]
        if key not in keys:
            raise ValueError("Unexpected saved trade")
        trade = ClosedTrade(**{k: v for k, v in raw.items() if k not in {"name", "phase", "fold"}})
        scenario = plan["stress_costs" if raw["phase"].endswith("stress") else "costs"]
        if not math.isclose(trade.commission_cost_money, 2*trade.volume*scenario["commission_per_lot"], abs_tol=1e-9):
            raise ValueError("Incorrect per-side commission")
        if not math.isclose(trade.gross_pnl_money-trade.commission_cost_money-trade.spread_cost_money
                            -trade.slippage_cost_money, trade.pnl_money, abs_tol=1e-8):
            raise ValueError("Cost components do not reconcile")
        if (trade.side == "BUY" and trade.exit_sl < trade.sl_initial) or (
                trade.side == "SELL" and trade.exit_sl > trade.sl_initial):
            raise ValueError("A protective stop widened")
        grouped[key].append(trade)
    info = SymbolTradeInfo(**plan["symbol_info"])
    for row in rows:
        trades = grouped[(row["name"], row["phase"], row["fold"])]
        for trade in trades:
            if not row["start"] <= trade.entry_time_utc < row["end_exclusive"] or not (
                    trade.entry_time_utc <= trade.exit_time_utc <= row["end_exclusive"]):
                raise ValueError("Trade outside replay boundary")
        actual = record_metrics(trades, settings[row["name"]], info)
        _equal({key: row[key] for key in actual}, actual)
    for name, scopes in report["comparison"].items():
        for scope, phase, indices in (("earlier_year", "earlier_base", {0}),
            ("earlier_year_stress", "earlier_stress", {0}), ("test_year", "test_base", set(range(1, 13))),
            ("confirmation", "test_base", set(range(7, 13))), ("stress_confirmation", "test_stress", set(range(7, 13)))):
            relevant = [r for r in rows if r["name"] == name and r["phase"] == phase and r["fold"] in indices]
            trades = [t for r in relevant for t in grouped[(name, phase, r["fold"])]]
            actual = {"metrics": trade_metrics(trades, 10000), "loss_streaks": loss_streaks(trades),
                "volumes": dict(sorted(Counter(f"{t.volume:g}" for t in trades).items())),
                "at_lot_cap": sum(r["at_lot_cap"] for r in relevant),
                "max_initial_stop_risk_pct": max(r["max_initial_stop_risk_pct"] for r in relevant),
                "max_initial_stop_risk_money": max(r["max_initial_stop_risk_money"] for r in relevant)}
            _equal(scopes[scope], actual)
    return {"passed": True, "replays": len(rows), "saved_trade_records": len(raw_trades),
            "checks": ["all scenarios and windows complete", "fixed lot/stop/daily/portfolio protections",
                       "cost reconciliation and per-side commission", "no widened stops or overlapping trades",
                       "entry-equity risk reconstruction per replay", "loss streaks, drawdowns and all summaries recomputed"],
            "live_risk_selected": None}


def render(report: dict) -> str:
    c = report["comparison"]
    lines = ["# USDCHF: larger risk budgets with fixed protection caps", "",
             "**Applied to offline simulations only. No live risk level selected; active configurations unchanged.**", "",
             "Declared budgets are 0.1%, 0.2%, 0.3% and 0.5%. All keep the 0.05 maximum lot, original initial "
             "stop/exits, daily loss limit and portfolio cap. Results come from full replays, not multiplied past P&L.", ""]
    plateau = all(c[f"{ref}_risk_0.2"] == c[f"{ref}_risk_{risk:g}"] for ref in REFERENCES for risk in (.3, .5))
    if plateau:
        lines += ["**Budgets of 0.2%, 0.3% and 0.5% produce identical outcomes in this study because the lot cap binds.**", ""]
    lines += ["## Twelve monthly test windows", "",
              "Each window starts flat with EUR 10,000; summed monthly returns are not continuous compounding. "
              "Both references and these dates were already observed before this sizing study.", "",
              "| Reference | Declared risk % | Volumes (lot: trades) | Maximum actual initial risk % | Net EUR | Realized DD EUR | Longest losing run | Worst losing-run loss EUR |",
              "|---|---:|---|---:|---:|---:|---:|---:|"]
    for reference in REFERENCES:
        for risk in RISK_LEVELS:
            r = c[f"{reference}_risk_{risk:g}"]["test_year"]
            m, s = r["metrics"], r["loss_streaks"]
            volumes = ", ".join(f"{v}: {n}" for v, n in r["volumes"].items()) or "none"
            lines.append(f'| {reference} | {risk:g} | {volumes} | {r["max_initial_stop_risk_pct"]:.4f} | '
                         f'{m["net_pnl"]:.2f} | {m["max_realized_drawdown"]:.2f} | '
                         f'{s["max_consecutive_losses"]} | {s["worst_loss_streak_money"]:.2f} |')
    lines += ["", "Actual initial risk is entry-to-stop price exposure against each replay's entry equity, "
              "excluding commissions, exit slippage and gaps. It is not a maximum possible loss. "
              "Streaks across monthly resets are descriptive; per-replay streaks are retained in report.json.", "",
              "## Earlier losing year and cost stress", "",
              "The earlier year is a separate continuous replay, 15 November 2024 to 15 November 2025 exclusive. "
              "It is not an overlapping sum of training windows. Later-six results cover 15 May to 11 November 2026 exclusive.", "",
              "| Reference | Budget % | Earlier net EUR | Earlier DD EUR | Earlier stressed net EUR | Later-six net EUR | Later-six stressed net EUR |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for reference in REFERENCES:
        for risk in RISK_LEVELS:
            r = c[f"{reference}_risk_{risk:g}"]
            early, early_stress, later, stress = (r[s]["metrics"] for s in (
                "earlier_year", "earlier_year_stress", "confirmation", "stress_confirmation"))
            lines.append(f'| {reference} | {risk:g} | {early["net_pnl"]:.2f} | '
                         f'{early["max_realized_drawdown"]:.2f} | {early_stress["net_pnl"]:.2f} | '
                         f'{later["net_pnl"]:.2f} | {stress["net_pnl"]:.2f} |')
    lines += ["", "Increasing position size scales losing periods too; it does not establish a stronger entry edge. "
              "A positive later test year cannot erase the earlier-year evidence or justify live promotion.", "",
              "## Protocol, protections and limitations", "",
              "- USDCHF M30 setups, explicit M1 confirmation with 300-bar context. References: original spread cap 1.8 pips and previously tested tighter 0.9-pip cap.",
              "- " + report["plan"]["unchanged"],
              "- The eight settings and windows were registered before replay; no risk budget is nominated for live use.",
              "- Twelve nonoverlapping monthly tests, 16 November 2025 to 11 November 2026 exclusive; later six also replayed under cost stress.",
              "- Observed spreads, assumed EUR 3.50/lot/side commission and 0.2-pip adverse market/stop slippage. "
              "Stress doubles commission/slippage to EUR 7.00 and 0.4 pip. Observed spreads stay unchanged; missing-spread fallback doubles from 1 to 2 pips.",
              "- **Swap/overnight financing is not included.** This study isolates sizing while preserving prior cost comparability.",
              "- Realized cash-flow drawdown is not intratrade equity drawdown or a future loss bound."]
    lines += ["- " + note for note in report["plan"]["limitations"]]
    lines += ["- Saved history only. Broker connections and order methods are blocked. No bot started, no trades placed, no active configuration changed.",
              "", "## Reproduce and audit", "", "```powershell",
              r".\.venv\Scripts\python.exe -m src.tools.research_risk_levels --workers 6",
              r".\.venv\Scripts\python.exe -m src.tools.render_risk_levels reports/usdchf_risk_levels/report.json",
              "```", "", "plan.json freezes configuration and data/code hashes. report.json contains all 160 "
              "replay rows and five scope summaries per configuration. trades.json contains all saved simulated "
              "fills; audit.json reconstructs entry equity, risk, costs, drawdown and loss streaks.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    trades = json.loads(args.report.with_name("trades.json").read_text(encoding="utf-8"))
    result = audit(report, trades)
    args.report.with_name("audit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    args.report.with_name("README.md").write_text(render(report), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
