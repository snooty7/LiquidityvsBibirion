"""Audit saved test trades and render the three-family USDCHF study."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path

from src.tools.backtest_mt5 import ClosedTrade
from src.tools.walk_forward import trade_metrics


def audit(report: dict, trades: list[dict]) -> dict:
    """Recompute every test row and summary, and verify costs and trade boundaries."""
    grouped = defaultdict(list)
    settings = {v["name"]: v["settings"] for v in report["plan"]["variants"]}
    for raw in trades:
        trade = ClosedTrade(**{key: value for key, value in raw.items() if key not in {"fold", "name", "scenario"}})
        cfg = settings[raw["name"]]
        if not 0 < trade.volume <= cfg["max_lot"]:
            raise ValueError("Trade exceeds unchanged lot cap")
        if cfg["trade_side_filter"] != "both" and trade.side.lower() != cfg["trade_side_filter"]:
            raise ValueError("Trade bypassed direction filter")
        if trade.side == "BUY" and trade.exit_sl < trade.sl_initial:
            raise ValueError("BUY stop widened")
        if trade.side == "SELL" and trade.exit_sl > trade.sl_initial:
            raise ValueError("SELL stop widened")
        if not math.isclose(trade.gross_pnl_money-trade.spread_cost_money-trade.commission_cost_money
                            -trade.slippage_cost_money, trade.pnl_money, abs_tol=1e-8):
            raise ValueError("Trade costs do not reconcile")
        scenario = report["plan"]["stress_costs" if raw["scenario"] == "stress" else "costs"]
        if not math.isclose(trade.commission_cost_money, 2*trade.volume*scenario["commission_per_lot"], abs_tol=1e-9):
            raise ValueError("Commission does not match registered per-side costs")
        grouped[(raw["fold"], raw["name"], raw["scenario"])].append(trade)

    def verify(expected, actual):
        for key, value in expected.items():
            other = actual[key]
            if isinstance(value, (float, int)) and value is not None:
                if not math.isclose(value, other, rel_tol=1e-10, abs_tol=1e-8):
                    raise ValueError(f"Recomputed metric differs: {key}")
            elif value != other:
                raise ValueError(f"Recomputed metric differs: {key}")

    test_rows = [r for r in report["rows"] if r["phase"] == "test"]
    keys = {(row["fold"], row["name"], row["scenario"]) for row in test_rows}
    if set(grouped)-keys:
        raise ValueError("Unexpected test trade group")
    for row in test_rows:
        group = grouped[(row["fold"], row["name"], row["scenario"])]
        for trade in group:
            if not row["start"] <= trade.entry_time_utc < row["end_exclusive"]:
                raise ValueError("Entry outside test boundary")
            if not trade.entry_time_utc <= trade.exit_time_utc <= row["end_exclusive"]:
                raise ValueError("Outcome outside test boundary")
        verify(row["metrics"], trade_metrics(group, 10000))
    for name, scopes in report["comparison"].items():
        for scope, record in scopes.items():
            indices = range(1, 13) if scope == "aggregate" else range(7, 13)
            scenario = "stress" if scope == "stress_confirmation" else "base"
            combined = [t for index in indices for t in grouped[(index, name, scenario)]]
            verify(record["metrics"], trade_metrics(combined, 10000))
    return {"passed": True, "test_rows_recomputed": len(test_rows), "test_trade_records": len(trades),
            "checks": ["test boundaries", "all cost components reconcile", "per-side commission",
                       "unchanged maximum lot", "side eligibility", "stops never widened",
                       "every test row and aggregate independently recomputed"]}


def render(report: dict) -> str:
    """Keep the descriptive profit winner separate from frozen training promotion."""
    comparison = report["comparison"]
    names = report["descriptive_ranking"]["aggregate"]
    winner = names[0]
    m = comparison[winner]["aggregate"]["metrics"]
    policies = report["policies"]
    eligible = [name for name, p in policies.items() if p["promotion_passed"]]
    lines = ["# USDCHF M30 / M1: three strategy ideas", "",
             f'**Highest descriptive full-test net: `{winner}`, EUR {m["net_pnl"]:.2f} ({m["return_pct"]:.3f}%).**', "",
             "**Promotion:** " + (", ".join(eligible) + " passed the declared historical gates." if eligible else
                                     "no training-nominated upgrade passed all gates."), "",
             "This ranking reports all six predeclared hypotheses, including rejected training candidates. "
             "It cannot override the frozen training nominations. These dates and side results were already "
             "examined; this is exploratory historical research, not untouched future validation.", "",
             "## Which idea earns most?", "",
             "| Family | Best full-test model (descriptive) | Net EUR | Later-six net EUR | Stressed later-six net EUR |",
             "|---|---|---:|---:|---:|"]
    for family in ("direction", "spread", "exit"):
        members = [v["name"] for v in report["plan"]["variants"] if v["family"] == family]
        name = next(n for n in names if n in members)
        c = comparison[name]
        lines.append(f'| {family} | {name} | {c["aggregate"]["metrics"]["net_pnl"]:.2f} | '
                     f'{c["confirmation"]["metrics"]["net_pnl"]:.2f} | '
                     f'{c["stress_confirmation"]["metrics"]["net_pnl"]:.2f} |')
    lines += ["", "## All predeclared models: twelve test windows", "",
              "| Model | Trades | Gross EUR | Spread EUR | Commission EUR | Slippage EUR | Net EUR | Return | PF | Realized DD EUR |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name in names:
        m = comparison[name]["aggregate"]["metrics"]
        pf = f'{m["profit_factor"]:.3f}' if m["profit_factor"] is not None else "n/a"
        lines.append(f'| {name} | {m["trades"]} | {m["gross_pnl"]:.2f} | {m["spread_cost"]:.2f} | '
                     f'{m["commission_cost"]:.2f} | {m["slippage_cost"]:.2f} | {m["net_pnl"]:.2f} | '
                     f'{m["return_pct"]:.3f}% | {pf} | {m["max_realized_drawdown"]:.2f} |')
    lines += ["", "## Later six windows and cost stress", "",
              "| Model | Trades | Base net EUR | Base realized DD EUR | Stress net EUR | Stress realized DD EUR |",
              "|---|---:|---:|---:|---:|---:|"]
    for name in names:
        base, stress = (comparison[name][s]["metrics"] for s in ("confirmation", "stress_confirmation"))
        lines.append(f'| {name} | {base["trades"]} | {base["net_pnl"]:.2f} | '
                     f'{base["max_realized_drawdown"]:.2f} | {stress["net_pnl"]:.2f} | '
                     f'{stress["max_realized_drawdown"]:.2f} |')
    lines += ["", "## Frozen training nominations and promotion", "",
              "Fixed nominations use only the first six preceding training windows. They cannot use later "
              "training/test winners. Aggregate fixed results include development overlap and are descriptive; "
              "the later six windows are the within-study confirmation subset. All dates were previously observed.", "",
              "| Selection group | Fixed training choice | Full-test net EUR | Later-six net EUR | Stressed later-six net EUR | Promoted? |",
              "|---|---|---:|---:|---:|---|"]
    for family, policy in policies.items():
        f = policy["fixed"]
        lines.append(f'| {family} | {policy["fixed_name"]} | {f["aggregate"]["metrics"]["net_pnl"]:.2f} | '
                     f'{f["confirmation"]["metrics"]["net_pnl"]:.2f} | '
                     f'{f["stress_confirmation"]["metrics"]["net_pnl"]:.2f} | '
                     f'{"YES" if policy["promotion_passed"] else "NO"} |')
    lines += ["", "| Gate | direction | spread | exit | overall |", "|---|---|---|---|---|"]
    for gate in policies["overall"]["promotion_gates"]:
        lines.append("| " + gate + " | " + " | ".join(
            "PASS" if policies[family]["promotion_gates"][gate] else "FAIL"
            for family in ("direction", "spread", "exit", "overall")) + " |")
    lines += ["", "### Fixed nomination evidence", "",
              "Overlapping training-window sums are selection diagnostics, not independent account returns.", "",
              "| Candidate | Sum training net EUR | Sum realized DD EUR | Windows with >=20 trades | Rejection reasons |",
              "|---|---:|---:|---:|---|"]
    for name, d in report["locked_selections"]["overall"]["fixed_diagnostics"].items():
        reasons = "; ".join(d["rejections"]) or "eligible"
        lines.append(f'| {name} | {d["net_sum"]:.2f} | {d["drawdown_sum"]:.2f} | '
                     f'{d["windows_with_20_trades"]}/6 | {reasons} |')
    lines += ["", "## Adaptive policies (each fold chooses from its own prior training)", "",
              "| Group | Full-test net EUR | Later-six net EUR | Stressed later-six net EUR |",
              "|---|---:|---:|---:|"]
    for family, p in policies.items():
        a = p["adaptive"]
        lines.append(f'| {family} | {a["aggregate"]["metrics"]["net_pnl"]:.2f} | '
                     f'{a["confirmation"]["metrics"]["net_pnl"]:.2f} | '
                     f'{a["stress_confirmation"]["metrics"]["net_pnl"]:.2f} |')
    lines += ["", "Adaptive performance is reported separately; it does not approve a fixed profile or bypass promotion gates.", "",
              "| Fold | Test start UTC | Direction choice | Spread choice | Exit choice | Overall choice |",
              "|---:|---|---|---|---|---|"]
    for fold in report["plan"]["folds"]:
        i = str(fold["index"])
        choices = [report["locked_selections"][family]["adaptive"][i]["selected"]
                   for family in ("direction", "spread", "exit", "overall")]
        lines.append(f'| {i} | {fold["test_start"][:10]} | ' + " | ".join(choices) + " |")
    lines += ["", "## Protocol", "",
              "- USDCHF M30 setups / M1 confirmation with 300-bar context; native broker candles from the saved snapshot.",
              "- Twelve 30-day tests, 16 November 2025 through 10 November 2026 UTC; 365 preceding training days and one-day embargo per fold.",
              "- Base: observed historical spread, EUR 3.50/lot/side commission, 0.2-pip adverse market/stop slippage. "
              "Stress: EUR 7.00 and 0.4 pip; observed spreads unchanged and missing-spread fallback doubled from 1 to 2 pips.",
              "- " + report["plan"]["unchanged_risk"],
              "- " + report["plan"]["engine_alignment"],
              "- Seven fixed models only (baseline plus two per idea). No combinations or post-result parameter changes.",
              "- Training nominations and gates were pushed before test replay. A prereplay JSON-container normalization amendment is recorded alongside the initial registration."]
    lines += ["- " + s for s in report["plan"]["limitations"]]
    lines += ["- Saved-history research blocks MT5 initialization/order methods. No bot started, no orders sent, no active profile changed.",
              "", "## Reproduction and audit", "", "```powershell",
              r".\.venv\Scripts\python.exe -m src.tools.research_usdchf_three_ideas --history history/mt5_20261111/USDCHF_extended.json --output reports/usdchf_three_ideas --workers 6",
              r".\.venv\Scripts\python.exe -m src.tools.render_usdchf_three_ideas reports/usdchf_three_ideas/report.json",
              "```", "", "`plan.json` preserves the protocol, costs and code/data hashes; `locked_selections.json` "
              "records training choices. `report.json` includes every train/test/stress metric row. "
              "`test_trades.json` exposes exact test trade outcomes and cost components. `audit.json` records "
              "the independent reconstruction of all test rows and summaries, boundary/cost checks and stop/lot caps.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    trades = json.loads(args.report.with_name("test_trades.json").read_text(encoding="utf-8"))
    result = audit(report, trades)
    args.report.with_name("audit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    args.report.with_name("README.md").write_text(render(report), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
