"""Known-cost benchmark and full continuous accounts; preserves the original nomination."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from src.backtesting.costs import ExecutionCosts
from src.services.config import SymbolConfig
from src.tools.research_loss_reduction import initialize, worker
from src.tools.research_usdchf_m30 import _forbid_broker
from src.tools.research_usdchf_three_ideas import register
from src.tools.walk_forward import default_config_paths, discover_branches


def render(report):
    lines = ["# USDCHF EUR20k: continuous loss-reduction comparison", "",
        "All accounts below start with EUR20,000 and run continuously, with **no monthly resets**. "
        "Risk is 0.5% per entry. Figures include modeled spread, commission and slippage; **swap/financing is excluded**.", "",
        "## One account through the full history", "",
        "15 November 2024 to 11 November 2026 exclusive. This includes the bad and better periods in one account.", "",
        "| Model | Start EUR | End EUR | Net EUR | Maximum M1-close equity drawdown EUR | Mean winner EUR | EUR100-200 winners | Trades |",
        "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, phases in report["known_cost_benchmark"]["full_accounts"].items():
        r = phases["full"]
        lines.append(f'| {name} | 20000.00 | {r["account"]["end_equity"]:.2f} | {r["metrics"]["net_pnl"]:.2f} | '
            f'{r["account"]["m1_close_drawdown"]:.2f} | {r["mean_winner"]:.2f} | '
            f'{r["wins_100_to_200"]} | {r["metrics"]["trades"]} |')
    comparisons = dict(report["comparison"])
    comparisons["known_spread_0_9"] = report["known_cost_benchmark"]["separate_periods"]
    for phase, title in (("earlier", "Earlier bad period: 15 Nov 2024 to 15 Nov 2025 exclusive"),
                         ("later", "Later period: 16 Nov 2025 to 11 Nov 2026 exclusive")):
        lines += ["", "## " + title, "",
            "Each row is a separate continuous account, starting at EUR20,000 at the beginning of this period.", "",
            "| Model | End EUR | Net EUR | Maximum M1-close equity drawdown EUR | Mean winner EUR | EUR100-200 winners | Trades |",
            "|---|---:|---:|---:|---:|---:|---:|"]
        for name, phases in comparisons.items():
            r = phases[phase]
            lines.append(f'| {name} | {r["account"]["end_equity"]:.2f} | {r["metrics"]["net_pnl"]:.2f} | '
                f'{r["account"]["m1_close_drawdown"]:.2f} | {r["mean_winner"]:.2f} | '
                f'{r["wins_100_to_200"]} | {r["metrics"]["trades"]} |')
    lines += ["", "## Doubled commission/slippage", "",
        "| Model | Earlier stressed net EUR | Later stressed net EUR |",
        "|---|---:|---:|"]
    for name, phases in comparisons.items():
        lines.append(f'| {name} | {phases["earlier_stress"]["metrics"]["net_pnl"]:.2f} | '
                     f'{phases["later_stress"]["metrics"]["net_pnl"]:.2f} |')
    lines += ["", "| Full-history account | Stressed end EUR | Stressed net EUR | Stressed M1-close equity drawdown EUR |",
              "|---|---:|---:|---:|"]
    for name, phases in report["known_cost_benchmark"]["full_accounts"].items():
        r = phases["full_stress"]
        lines.append(f'| {name} | {r["account"]["end_equity"]:.2f} | {r["metrics"]["net_pnl"]:.2f} | '
                     f'{r["account"]["m1_close_drawdown"]:.2f} |')
    lines += ["", "## Rules and interpretation", ""]
    lines += [f'- `{n}`: {d}' for n, d in report["plan"]["hypotheses"].items()]
    lines += ["- `known_spread_0_9`: original reference with spread <=0.9 pip. This threshold and its earlier favorable comparisons were already known; it is a control, not a new discovery. No parameter search was performed for this addendum.",
        "- The original earlier-period nomination remains `" + report["locked_selection"]["selected"] + "`. "
        "The known-cost addendum does not rerank or alter it. All candidates remain visible; no sample-count gate hides results.",
        "- Full accounts carry cash, positions and guard state through the entire history, including the calendar gap between the two separately reported periods.",
        "- Equity drawdown is the fall from a previous account-equity peak, including floating P&L at observed M1 closes, incurred entry fees and actual simulated exits. Intrabar/tick losses can be greater. Drawdown is already part of the path; it is not subtracted from net profit again.",
        "- Mean winner is calculated only over positive-net trades. Count in EUR100-200 is disclosed separately; not every winner reaches that band.",
        "- Base costs: historical spread, EUR3.50/lot/side assumed commission, 0.2-pip adverse market/stop slippage. Stress doubles commission/slippage to EUR7.00/0.4 pip, leaves observed spread unchanged, and doubles missing-spread fallback from 1 to 2 pips.",
        "- " + report["plan"]["risk_fixed"]]
    lines += ["- " + n for n in report["plan"]["limitations"]]
    lines += ["- No live configuration changed, no broker connection during replay, no bot started and no orders placed.", "",
        "## Reproduce", "", "```powershell", "python -m src.tools.research_loss_reduction --workers 4",
        "python -m src.tools.complete_loss_reduction --workers 4", "```", "",
        "The original protocol is plan.json; original older-data choice is locked_selection.json. "
        "cost_benchmark/plan.json registers the separate known-reference completion. report.json retains "
        "all actual simulated trades and both original and addendum results.", ""]
    return "\n".join(lines)


def run(output, path, workers=4, register_only=False):
    _forbid_broker()
    original_plan = json.loads((output/"plan.json").read_text(encoding="utf-8"))
    source = next(b for b in discover_branches(default_config_paths()) if b.branch_id == "92024-USDCHF-M30-3c27c3d9")
    cfg = SymbolConfig(**original_plan["settings"]["baseline"])
    start = original_plan["windows"]["earlier"]["start"]
    end = original_plan["windows"]["later"]["end_exclusive"]
    plan = {"registered_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Add already-known spread<=0.9 benchmark and full-history continuous accounts. No tuning, no new discovery, no change to original nomination.",
        "history_sha256": original_plan["history_sha256"],
        "original_plan_sha256": hashlib.sha256((output/"plan.json").read_bytes()).hexdigest(),
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "full_history": {"start": start, "end_exclusive": end},
        "settings_changes": {"known_spread_0_9": {"max_spread_pips": .9}},
        "tasks": "Four known-cost separate-period base/stress replays and four full-history baseline/known-cost base/stress replays; all EUR20k, 0.5% risk, original exits/guards.",
        "broker_connections": False, "trading_calls": False}
    plan = register(plan, output/"cost_benchmark")
    if register_only:
        print("Registered known-cost control and full-history accounts; original nomination preserved", flush=True)
        return plan
    report = json.loads((output/"report.json").read_text(encoding="utf-8"))
    locked = deepcopy(report["locked_selection"])
    tasks = []
    costs, stress = ExecutionCosts(**original_plan["costs"]), ExecutionCosts(**original_plan["stress_costs"])
    for label, window in original_plan["windows"].items():
        for scenario, suffix in ((costs, ""), (stress, "_stress")):
            tasks.append(("known_spread_0_9", label+suffix, source.config, replace(cfg, max_spread_pips=.9),
                          datetime.fromisoformat(window["start"]), datetime.fromisoformat(window["end_exclusive"]), scenario))
    for name, settings in (("baseline", cfg), ("known_spread_0_9", replace(cfg, max_spread_pips=.9))):
        for scenario, phase in ((costs, "full"), (stress, "full_stress")):
            tasks.append((name, phase, source.config, settings, datetime.fromisoformat(start), datetime.fromisoformat(end), scenario))
    results = []
    with ProcessPoolExecutor(max_workers=workers, initializer=initialize, initargs=(str(path),)) as pool:
        futures = [pool.submit(worker, task) for task in tasks]
        for index, future in enumerate(as_completed(futures), 1):
            r = future.result()
            results.append(r)
            print(r["name"], r["phase"], f"{index}/{len(futures)}", flush=True)
    report["known_cost_benchmark"] = {"plan": plan,
        "separate_periods": {r["phase"]: r for r in results if not r["phase"].startswith("full")},
        "full_accounts": {name: {r["phase"]: r for r in results if r["name"] == name and r["phase"].startswith("full")}
                          for name in ("baseline", "known_spread_0_9")}}
    if report["locked_selection"] != locked:
        raise ValueError("Original nomination changed")
    (output/"report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    (output/"README.md").write_text(render(report), encoding="utf-8")
    print("FINISHED known-cost completion", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("reports/usdchf_loss_reduction"))
    parser.add_argument("--history", type=Path, default=Path("history/mt5_20261111/USDCHF_extended.json"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--register-only", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("workers must be positive")
    run(args.output, args.history, args.workers, args.register_only)


if __name__ == "__main__":
    main()
