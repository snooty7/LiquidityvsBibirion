"""Audit and present the independently simulated H1/H4 FX research accounts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.tools.render_usdchf_three_ideas import audit as audit_account
from src.tools.research_fx_htf import SYMBOLS, MODELS


def audit(report: dict, trades: list[dict]) -> dict:
    """Require every registered replay, then reconstruct each account separately."""
    expected = {(symbol, name, index, phase, scenario)
                for symbol in SYMBOLS for name in MODELS
                for phase, scenario, indices in (("train", "base", range(1, 13)),
                    ("test", "base", range(1, 13)), ("test", "stress", range(7, 13)))
                for index in indices}
    rows = report["rows"]
    actual = {(r["symbol"], r["name"], r["fold"], r["phase"], r["scenario"]) for r in rows}
    if actual != expected or len(rows) != len(expected) or report["unique_replays"] != len(expected):
        raise ValueError("Missing, duplicate or unexpected FX study replay")
    if any(t["symbol"] not in SYMBOLS for t in trades):
        raise ValueError("Unexpected trade symbol")
    result = {}
    for symbol in SYMBOLS:
        plan = report["plan"]
        subset = {"plan": {"variants": [{"name": name, "settings": cfg}
                                           for name, cfg in plan["settings"][symbol].items()],
                           "costs": plan["costs"], "stress_costs": plan["stress_costs"]},
                  "rows": [r for r in rows if r["symbol"] == symbol],
                  "comparison": report["comparison"][symbol]}
        result[symbol] = audit_account(subset, [t for t in trades if t["symbol"] == symbol])
    return {"passed": True, "all_replays_present": len(expected), "accounts_audited_separately": result,
            "no_portfolio_return_inferred": True}


def render(report: dict) -> str:
    comparison, policies = report["comparison"], report["policies"]
    ranks = report["descriptive_ranking"]["aggregate"]
    best_new = next(row for row in ranks if row["model"] != "baseline")
    lines = ["# FX H1/H4: trend pullback and confirmed range breakout", "",
             f'**Highest descriptive new-model net: {best_new["symbol"]} / `{best_new["model"]}`, EUR {best_new["net_pnl"]:.2f}.**', "",
             "All profits below are after modeled spread, commission and slippage. **Swap/overnight financing "
             "is not included.** Overnight trade counts are disclosed. Results are research-only, with no live "
             "deployment approval. Historical dates were previously examined and are not untouched future data.", "",
             "Overnight counts flag changes of UTC calendar date; they are not exact broker rollover counts.", "",
             "Each pair/model is an independent EUR 10,000 simulation. Do not add these returns into a "
             "single EUR 10,000 account or infer a combined portfolio result.", "",
             "## All nine independent accounts: twelve test windows", "",
             "| Pair | Model | Trades | Net EUR | Return | PF | Realized DD EUR | Overnight trades |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    if all(comparison[s][n]["aggregate"]["metrics"]["net_pnl"] <= 0 for s in SYMBOLS for n in MODELS[1:]):
        lines[4:4] = ["**Neither new fixed model produced positive full-period net on any of the three pairs.**", ""]
    for row in ranks:
        symbol, name = row["symbol"], row["model"]
        record = comparison[symbol][name]["aggregate"]
        m = record["metrics"]
        pf = "n/a" if m["profit_factor"] is None else f'{m["profit_factor"]:.3f}'
        lines.append(f'| {symbol} | {name} | {m["trades"]} | {m["net_pnl"]:.2f} | '
                     f'{m["return_pct"]:.3f}% | {pf} | {m["max_realized_drawdown"]:.2f} | '
                     f'{record["overnight_trades"]} |')
    lines += ["", "## Later-six confirmation subset and doubled commission/slippage", "",
              "| Pair | Model | Trades | Confirmation net EUR | Stressed net EUR | Stressed realized DD EUR |",
              "|---|---|---:|---:|---:|---:|"]
    for row in ranks:
        s, n = row["symbol"], row["model"]
        c, stress = (comparison[s][n][scope]["metrics"] for scope in ("confirmation", "stress_confirmation"))
        lines.append(f'| {s} | {n} | {c["trades"]} | {c["net_pnl"]:.2f} | {stress["net_pnl"]:.2f} | '
                     f'{stress["max_realized_drawdown"]:.2f} |')
    lines += ["", "## Cost reconciliation: full test period", "",
              "| Pair | Model | Gross EUR | Spread EUR | Commission EUR | Slippage EUR | Net EUR |",
              "|---|---|---:|---:|---:|---:|---:|"]
    for row in ranks:
        s, n = row["symbol"], row["model"]
        m = comparison[s][n]["aggregate"]["metrics"]
        lines.append(f'| {s} | {n} | {m["gross_pnl"]:.2f} | {m["spread_cost"]:.2f} | '
                     f'{m["commission_cost"]:.2f} | {m["slippage_cost"]:.2f} | {m["net_pnl"]:.2f} |')
    lines += ["", "## Frozen training nominations", "",
              "Fixed nominations use only the first six prior training windows. Their full-period results "
              "include development overlap; the later six windows are the within-study confirmation subset. "
              "Neither test-period winners nor later training windows can change the fixed nomination.", "",
              "| Pair | Fixed choice | Declared historical gates | Failed gates |",
              "|---|---|---|---|"]
    for symbol, p in policies.items():
        failed = "; ".join(gate for gate, passed in p["promotion_gates"].items() if not passed) or "none"
        lines.append(f'| {symbol} | {p["fixed_name"]} | {"PASS" if p["promotion_passed"] else "FAIL"} | {failed} |')
    lines += ["", "A historical gate pass is not live approval: financing assumptions, fresh forward evidence "
              "and execution fidelity still require validation.", "",
              "| Pair | Candidate | Training net sum EUR | Training DD sum EUR | Windows >=20 trades | Rejection reasons |",
              "|---|---|---:|---:|---:|---|"]
    for symbol, choice in report["locked_selections"].items():
        for name, d in choice["fixed_diagnostics"].items():
            reason = "; ".join(d["rejections"]) or "eligible"
            lines.append(f'| {symbol} | {name} | {d["net_sum"]:.2f} | {d["drawdown_sum"]:.2f} | '
                         f'{d["windows_with_20_trades"]}/6 | {reason} |')
    lines += ["", "Training windows overlap; these sums are selection diagnostics, not independent account returns.", "",
              "## Adaptive training-selected policies", "",
              "These choose separately for each window using only its prior training data. Their results "
              "do not override fixed-profile promotion gates.", "",
              "| Pair | Full-period net EUR | Confirmation net EUR | Stressed confirmation net EUR |",
              "|---|---:|---:|---:|"]
    for symbol, p in policies.items():
        a = p["adaptive"]
        lines.append(f'| {symbol} | {a["aggregate"]["metrics"]["net_pnl"]:.2f} | '
                     f'{a["confirmation"]["metrics"]["net_pnl"]:.2f} | '
                     f'{a["stress_confirmation"]["metrics"]["net_pnl"]:.2f} |')
    lines += ["", "## Cross-market descriptive check", "",
              "| New model | Pairs positive over full tests | Pairs beating own baseline | Pairs positive under confirmation stress |",
              "|---|---:|---:|---:|"]
    for name in MODELS[1:]:
        positive = sum(comparison[s][name]["aggregate"]["metrics"]["net_pnl"] > 0 for s in SYMBOLS)
        improved = sum(comparison[s][name]["aggregate"]["metrics"]["net_pnl"] >
                       comparison[s]["baseline"]["aggregate"]["metrics"]["net_pnl"] for s in SYMBOLS)
        stress = sum(comparison[s][name]["stress_confirmation"]["metrics"]["net_pnl"] > 0 for s in SYMBOLS)
        lines.append(f'| {name} | {positive}/3 | {improved}/3 | {stress}/3 |')
    plan = report["plan"]
    lines += ["", "## Frozen rules and protocol", ""]
    lines += [f'- `{name}`: {note}' for name, note in plan["hypotheses"].items()]
    lines += ["- " + plan["baseline"], "- " + plan["ema_context"], "- " + plan["risk_unchanged"],
              "- Twelve nonoverlapping 30-day tests: 16 November 2025 through 10 November 2026 UTC. "
              "Each uses 365 preceding training days and a one-day embargo. First six prior training windows "
              "nominate the fixed model; last six test windows are the confirmation subset.",
              "- Every training and test window passed native history/indicator warm-up coverage checks before registration. "
              "Warm-up retrieval includes a calendar-week allowance for year-end holidays; missing bars are never fabricated.",
              "- Thresholds/parameters fixed before replay; one setting per new model, no tuning grid. "
              "All pairs' training choices locked before any test replay.",
              "- Base execution: historical spread; EUR 3.50/lot/side assumed commission, 0.2-pip adverse market/stop slippage. "
              "Stress doubles commission/slippage to EUR 7.00 and 0.4 pip. Historical spread is unchanged; missing-spread fallback doubles from 1 to 2 pips.",
              "- " + plan["history_access"]]
    lines += ["- " + note for note in plan["limitations"]]
    lines += ["- Saved-history replay explicitly blocks MT5 initialization and trading methods. No bot started, "
              "no orders placed, no active settings modified.", "", "## Reproduction and independent audit", "",
              "```powershell", r".\.venv\Scripts\python.exe -m src.tools.research_fx_htf --workers 4",
              r".\.venv\Scripts\python.exe -m src.tools.render_fx_htf reports/fx_htf/report.json", "```", "",
              "`plan.json` records source/data hashes, valuation snapshots and all settings. "
              "`locked_selections.json` holds prior-training evidence and choices. `report.json` has all 270 "
              "train/test/stress rows. `test_trades.json` exposes every test trade and its modeled costs. "
              "`audit.json` verifies completeness and independently reconstructs all 162 test/stress rows "
              "and account summaries, including boundaries, commission, lot caps and stop monotonicity.", ""]
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
