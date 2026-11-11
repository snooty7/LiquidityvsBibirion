"""Render the frozen long-filter study results without altering selection or gates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def render(report: dict) -> str:
    """Explain profit, failed constraints and study limitations from recorded results."""
    passed = report["promotion_passed"]
    lines = ["# USDCHF M30 / M1 long-entry filter", "",
             "**Decision: " + ("passes the declared historical gates." if passed else
                               "does not pass promotion; no upgrade approved.") + "**", "",
             "Profit after execution costs is the primary ranking objective. Risk sizing, initial stops, "
             "daily/exposure protection and trailing rules are unchanged. Active profiles keep the new filter off.", "",
             "## Cost-aware test results", "",
             "| Scope | Model | Trades | Net EUR | Return on EUR 10,000 | PF | Realized DD EUR |",
             "|---|---|---:|---:|---:|---:|---:|"]
    if not any(d["selected"] != "off" for d in report["selections"].values()):
        lines[6:6] = ["Neither threshold qualified in any training window. The filtered policy therefore "
                      "stayed off in every test window. Its test profits below are baseline profits, "
                      "not evidence that the filter improved performance. Standalone rejected thresholds "
                      "were not replayed on the test windows.", ""]
    for scope in ("aggregate", "confirmation", "stress_confirmation"):
        for name, record in report[scope].items():
            m = record["metrics"]
            pf = "n/a" if m["profit_factor"] is None else f'{m["profit_factor"]:.3f}'
            lines.append(f'| {scope} | {name} | {m["trades"]} | {m["net_pnl"]:.2f} | '
                         f'{m["return_pct"]:.3f}% | {pf} | {m["max_realized_drawdown"]:.2f} |')
    lines += ["", "Returns sum independent monthly folds, each starting flat with EUR 10,000; no compounding. "
              "Drawdown is realized cash-flow drawdown, not intratrade equity drawdown.", "",
              "| Scope | Model | BUY trades | BUY net EUR | SELL trades | SELL net EUR |",
              "|---|---|---:|---:|---:|---:|"]
    for scope in ("aggregate", "confirmation", "stress_confirmation"):
        for name, record in report[scope].items():
            buy, sell = record["sides"]["BUY"], record["sides"]["SELL"]
            lines.append(f'| {scope} | {name} | {buy["trades"]} | {buy["net_pnl"]:.2f} | '
                         f'{sell["trades"]} | {sell["net_pnl"]:.2f} |')
    lines += ["", "SELL rules are unchanged; fewer long positions can change which later SELL opportunities "
              "fit within the existing one-position limit.", "",
              "## Promotion gates", "", "| Gate | Result |", "|---|---|"]
    for gate, result in report["promotion_gates"].items():
        lines.append(f'| {gate} | {"PASS" if result else "FAIL"} |')
    lines += ["", "## Training decisions", "",
              "Each window fits two nonnegative thresholds (Q25/Q50) from baseline training BUY-entry features. "
              "The feature is H4 EMA20 rise over three closed bars divided by 14-bar mean true range, "
              "with a fixed 80-bar EMA context. Quantile fitting never uses profit labels. Full filtered "
              "training replays then choose the highest total net profit subject to positive BUY net, "
              "positive/improved total net, at least 20 retained BUY trades and drawdown <=1.25 baseline. "
              "If neither qualifies, the policy uses the unfiltered baseline.", "",
              "| Fold | Q25 threshold | Q50 threshold | Selected |", "|---:|---:|---:|---|"]
    for fold, decision in report["selections"].items():
        thresholds = decision["fit"]["thresholds"]
        lines.append(f'| {fold} | {thresholds.get("q25", "unavailable")} | '
                     f'{thresholds.get("q50", "unavailable")} | {decision["selected"]} |')
    lines += ["", "Overlapping training windows are selection diagnostics, not independent investment returns.", "",
              "| Fold | Candidate | Training net EUR | BUY trades | BUY net EUR | Realized DD EUR | Rejection reasons |",
              "|---:|---|---:|---:|---:|---:|---|"]
    for fold, decision in report["selections"].items():
        for name, record in decision["training"].items():
            m, buy = record["metrics"], record["buy_metrics"]
            reasons = "; ".join(decision["rejections"].get(name, []))
            if not reasons:
                reasons = "baseline" if name == "off" else "eligible"
            lines.append(f'| {fold} | {name} | {m["net_pnl"]:.2f} | {buy["trades"]} | '
                         f'{buy["net_pnl"]:.2f} | {m["max_realized_drawdown"]:.2f} | {reasons} |')
    lines += ["", "## Monthly test windows", "",
              "| Fold | Start UTC | Selection | Baseline net EUR | Policy net EUR |",
              "|---:|---|---|---:|---:|"]
    for f in report["per_fold"]:
        lines.append(f'| {f["fold"]} | {f["test_start"][:10]} | {f["selected"]} | '
                     f'{f["baseline"]["metrics"]["net_pnl"]:.2f} | '
                     f'{f["filtered_policy"]["metrics"]["net_pnl"]:.2f} |')
    lines += ["", "## Protocol and limitations", "",
              "- Twelve nonoverlapping 30-day tests from 16 November 2025 through 10 November 2026 UTC. "
              "Each has 365 preceding training days and a one-day embargo; later six windows are the confirmation subset.",
              "- Thresholds and choices were locked before test replay. No threshold tuning or gate relaxation after test results.",
              "- Historical bid candles and observed spreads, assumed EUR 3.50/lot/side commission, "
              "0.2-pip adverse market/stop slippage. Stress doubles commission/slippage to EUR 7.00 and 0.4 pip; "
              "observed spreads stay unchanged, with missing-spread fallback increasing from 1 to 2 pips.",
              "- " + report["plan"]["engine_alignment"],
              "- This freshly aligned M1 baseline supersedes earlier descriptive M1 numbers for comparison with this filter."]
    lines += ["- " + caveat for caveat in report["plan"]["caveats"]]
    lines += ["- Historical symbol valuation is held constant. Small gains are sensitive to unmodeled costs and execution effects.",
              "- Existing risk limits stay in place: 0.1% risk, 20-pip initial stop, 0.05 max lot, one position; no sizing increase.",
              "- Saved history only. Broker initialization and trading calls are blocked during research. No bot was started.",
              "", "Reproduce from the saved history:", "", "```powershell",
              r".\.venv\Scripts\python.exe -m src.tools.research_long_filter --history history/mt5_20261111/USDCHF_extended.json --output reports/usdchf_long_filter --workers 6",
              r".\.venv\Scripts\python.exe -m src.tools.render_long_filter_report reports/usdchf_long_filter/report.json",
              "```", "", "The plan, locked selections, per-fold results, costs and source/data hashes are recorded in the adjacent JSON files.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    args.report.with_name("README.md").write_text(render(report), encoding="utf-8")


if __name__ == "__main__":
    main()
