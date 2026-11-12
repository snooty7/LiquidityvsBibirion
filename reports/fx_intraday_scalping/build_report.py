"""Validate the completed offline ledgers and regenerate their human-readable report."""
import json
import math
from pathlib import Path

folder = Path(__file__).resolve().parent
report = json.loads((folder / "report.json").read_text())
plan, results = report["plan"], report["results"]
locked = json.loads((folder / "locked_selection.json").read_text())
accounts = [v for phases in results.values() for v in phases.values()]
assert len(accounts) == 48
for v in accounts:
    trades = v["trades"]
    assert math.isclose(v["account"]["end_equity"], 10000 + sum(t["pnl_money"] for t in trades), abs_tol=1e-7)
    assert v["wins_100_to_200"] == sum(100 <= t["pnl_money"] <= 200 for t in trades)
    assert v["no_overnight_and_no_swap"] and v["swap_net"] == 0
    assert v["financing_events"] == v["alternate_clock_financing_events"] == v["utc_overnight_trades"] == 0
    assert v["late_exits"] == 0 and v["max_actual_holding_minutes"] <= v["duration_minutes"]
    for t in trades:
        assert t["swap_money"] == 0 and t["swap_events"] == []
        assert math.isclose(t["gross_pnl_money"] - t["spread_cost_money"] - t["commission_cost_money"]
                            - t["slippage_cost_money"], t["pnl_money"], abs_tol=1e-8)
normal = [v["full"] for n, v in results.items() if not n.endswith("_stress")]
stress = [v["full"] for n, v in results.items() if n.endswith("_stress")]
assert len(normal) == len(stress) == 12
assert all(v["metrics"]["net_pnl"] < 0 for v in normal + stress)
best_normal = max(normal, key=lambda v: v["metrics"]["net_pnl"])
best_stress = max(stress, key=lambda v: v["metrics"]["net_pnl"])

lines = ["# Four-pair intraday scalping: EUR10,000, risk 0.75%, no swap", "",
    "**No tested configuration was profitable after modeled costs.** All twelve pair/duration configurations lost money under both normal and stressed costs. The least negative normal result was GBPUSD/15 minutes (-EUR825.83); under stress it was NZDUSD/15 minutes (-EUR1,570.87). These are losses, not profitable winners.", "",
    "**No-swap condition passed in all 48 accounts:** EUR0 financing, zero overnight positions and zero late exits. Nonzero broker swap rates remained active in the model; financing was not disabled or erased.", "",
    "The user changed the scope from SELL-only overnight avoidance to scalping with no overnight positions on either side. This study therefore closes BUY and SELL after 15/30/60 minutes. It retains the existing M30 liquidity/M1 confirmation entry family; it is not a newly designed M1-only signal.", "",
    "Common full period: **2025-09-01 00:00 UTC to 2026-11-11 00:00 UTC exclusive**, approximately 14 months. Every pair/duration/window starts independently at EUR10,000, risk 0.75%, with no monthly resets. Results cannot be added into a concurrently funded portfolio.", "",
    "## Earlier-selected duration per pair", "",
    "Earlier stressed net selected 15 minutes for each pair because it lost less during that earlier period. A negative nomination is not a profitability approval. All alternatives are also reported below.", "",
    "| Pair / holding limit | Normal net | Normal drawdown | Stressed net | Stressed drawdown | EUR100-200 winners normal/stressed | Trades normal/stressed |",
    "|---|---:|---:|---:|---:|---:|---:|"]
for pair, choice in locked.items():
    minutes = choice["selected_minutes"]
    a, b = (results[f"{pair}_{minutes}" + suffix]["full"] for suffix in ("", "_stress"))
    lines.append(f"| {pair} / {minutes}min | EUR{a['metrics']['net_pnl']:,.2f} | EUR{a['account']['m1_close_drawdown']:,.2f} | EUR{b['metrics']['net_pnl']:,.2f} | EUR{b['account']['m1_close_drawdown']:,.2f} | {a['wins_100_to_200']} / {b['wins_100_to_200']} | {a['metrics']['trades']} / {b['metrics']['trades']} |")
lines += ["", "Returns are for the full period, not monthly or annual. Drawdown includes open P&L at observed M1 closes, incurred entry fees and simulated fills; tick/intrabar drawdown can be greater. Target-band counts use individual net profit inclusive EUR100-200. Account profit includes all losses.", "",
    "## All twelve configurations", "",
    "| Pair | Minutes | Normal / stressed net | Normal / stressed drawdown | EUR100-200 winners normal/stressed | Normal / stressed win rate |",
    "|---|---:|---:|---:|---:|---:|"]
for pair in plan["pairs"]:
    for minutes in plan["durations_minutes"]:
        a, b = (results[f"{pair}_{minutes}" + suffix]["full"] for suffix in ("", "_stress"))
        lines.append(f"| {pair} | {minutes} | EUR{a['metrics']['net_pnl']:,.2f} / EUR{b['metrics']['net_pnl']:,.2f} | EUR{a['account']['m1_close_drawdown']:,.2f} / EUR{b['account']['m1_close_drawdown']:,.2f} | {a['wins_100_to_200']} / {b['wins_100_to_200']} | {a['metrics']['win_rate_pct']:.2f}% / {b['metrics']['win_rate_pct']:.2f}% |")
lines += ["", "## Earlier and later stressed accounts", "",
    "Earlier: 2025-09-01 to 2026-03-01 exclusive. Later: 2026-03-02 to 2026-11-11 exclusive. Each starts independently at EUR10,000; these values cannot be summed to reconstruct full-period compounding. Duration selection used earlier stressed net only, requiring trading participation and no financing/overnight violation; ties lower drawdown then name. It was locked before later/full results.", "",
    "| Pair | Minutes | Earlier stressed net | Later stressed net | Selected earlier |", "|---|---:|---:|---:|---|"]
for pair in plan["pairs"]:
    for minutes in plan["durations_minutes"]:
        phases = results[f"{pair}_{minutes}_stress"]
        lines.append(f"| {pair} | {minutes} | EUR{phases['earlier']['metrics']['net_pnl']:,.2f} | EUR{phases['later']['metrics']['net_pnl']:,.2f} | {'yes' if locked[pair]['selected_minutes'] == minutes else 'no'} |")
lines += ["", "## Normal-cost decomposition of selected models", "",
    "Gross price P&L is an accounting proxy before modeled costs, not an attainable zero-cost return.", "",
    "| Pair | Gross price P&L | Spread | Commission | Slippage | Net |", "|---|---:|---:|---:|---:|---:|"]
for pair, choice in locked.items():
    m = results[f"{pair}_{choice['selected_minutes']}"]["full"]["metrics"]
    values = [m[k] for k in ("gross_pnl", "spread_cost", "commission_cost", "slippage_cost", "net_pnl")]
    lines.append("| " + pair + " | " + " | ".join(f"EUR{x:,.2f}" for x in values) + " |")
lines += ["", "## Fixed execution and costs", "",
    "Both sides enter on weekdays 05:00 inclusive to 18:00 exclusive UTC, intersecting original strategy sessions. Exit after elapsed 15/30/60 wall-clock minutes or 19:00 UTC same day, whichever comes first. Missing quotes never create invented earlier fills; the first available actual M1 opening quote is used. Existing SL/TP already triggered at that opening quote takes priority over a timed market exit; daily protection retains priority.", "",
    "Risk-based size remains 0.75%, max lot 0.5, aggregate exposure cap 0.75%, EUR150 daily trigger and one-position rule. Initial SL20 pips, TP2R, trailing activation1.5R/gap1R with target removal, spread cap0.9 pips and original cooldown/filters are unchanged. No tightened stop is widened, no grid/averaging/martingale, and no pair-specific tuning was performed.", "",
    "Normal: observed historical spread, 1-pip missing-spread fallback, EUR3.50 commission/lot/side and 0.2-pip adverse market/stop slippage. Stress: EUR7, 0.4 pip, doubled negative financing debits and unchanged positive credits; missing-spread fallback becomes 2 pips. **Observed historical spreads are not doubled.** Take-profit limit exits have no exit slippage. Financing remained EUR0 in every account.", "",
    "Spread is the bid/ask difference; slippage is the difference between expected and actual execution price; swap is financing across rollover. In live trading, changing quotes and actual fills can differ from historical bar proxies. Stress is sensitivity analysis, not a prediction that live fees will be exactly double. These commission/slippage values are declared assumptions rather than a verified broker invoice. See [MT5 execution](https://www.metatrader5.com/en/terminal/help/trading/performing_deals) and [swap specifications](https://www.mql5.com/en/book/automation/symbols/symbols_swaps).", "",
    "## Data and financing audit", "",
    "The available exported FX universe is EURUSD, GBPUSD, NZDUSD and USDCHF; this is not every instrument offered by MT5. BTCUSDT is excluded. EURUSD/GBPUSD/USDCHF have longer exports, but original NZDUSD M1 data starts 2025-07-28. A read-only extension attempt returned only 98,879 recent M1 bars beginning 2026-08-06. That shorter download was archived separately and not substituted for the longer existing NZDUSD.json source. The common September2025 start gives equal horizons and individually verified warm-up. Plan.json records input names, per-pair EUR valuations and history hashes.", "",
    "The financing snapshot was captured from an already-running connected EUR MT5 session with Algo Trading disabled; no account ID, credentials or balance was saved. All four instruments have nonzero swap rates in the snapshot. Invalid MT5 triple-day code7 required the explicit prior Wednesday-triple assumption. Current rates are held constant across history, not reconstructed historical daily financing.", "",
    "All48 complete entry/exit paths have zero financing under both GMT+3 and an independent GMT+2 interval audit, zero overnight positions and zero late exits. The policy uses UTC deadlines, so absent financing under both schedules the alternate clock is path-equivalent. Any financed/overnight trade would be retained and disqualified, never silently set to zero or deleted.", "",
    "Each symbol uses its own positive EUR tick valuation/volume rules from historical exports. Valuation is constant, not a historical conversion series. Prices and some strategy dates were examined previously; earlier-only nomination does not create an untouched holdout. Three durations and one daylight window were fixed before outcomes. Pair rankings are descriptive. Historical margin, liquidity, latency, tick paths and changing minimum-stop constraints are not reconstructed.", "",
    "## Validation and reproduction", "",
    "**368 passed, one existing expected failure.** Twenty-one new cases cover intraday boundaries, weekends, elapsed deadlines, correct symbol history switching, nonambiguous broker symbols, rejection of no-trade/financed nominations, native SL/TP priority at gap opens, both directions/all durations, retained financing violations and real quote-gap exits. All trading tests use synthetic bars and forbid broker/order methods. Independent audit reconciles all48 account/cost ledgers and target-band counts.", "",
    "```powershell", "python -m src.tools.research_fx_scalping --history-root history/mt5_20261111 --snapshot reports/fx_intraday_scalping/swap_snapshot.json --output reports/fx_intraday_scalping --workers 6", "```", "",
    "The frozen plan records code/history hashes. Use a new output directory after a source/protocol change. Every research process forbids broker initialization/trading. No live settings changed, no bot was started and no order was placed."]
(folder / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
(folder / "swap_snapshot.json").write_text(json.dumps(plan["snapshot"], indent=2), encoding="utf-8")
checks = {"accounts": 48, "configurations": 12, "positive_normal": 0, "positive_stressed": 0,
    "overnight_positions": 0, "financing_events_both_clocks": 0, "late_exits": 0,
    "least_negative_normal": {"scenario": best_normal["scenario"], "net": best_normal["metrics"]["net_pnl"]},
    "least_negative_stressed": {"scenario": best_stress["scenario"], "net": best_stress["metrics"]["net_pnl"]},
    "tests_passed": 368, "expected_failures": 1}
(folder / "checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
print("All48 account/cost ledgers verified; report generated; no positive configurations")
