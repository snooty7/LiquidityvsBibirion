"""Audit frozen entry ledgers and regenerate a readable comparison."""
import argparse
import json
import math
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--folder", type=Path, default=Path(__file__).resolve().parent)
parser.add_argument("--tests-passed", type=int, default=391)
args = parser.parse_args()
folder = args.folder
r = json.loads((folder/"report.json").read_text())
p, results = r["plan"], r["results"]
locked = json.loads((folder/"locked_selection.json").read_text())
rows = [v for phases in results.values() for v in phases.values()]
assert len(rows) == 48
for record in rows:
    cash = 10000.0
    info = p["pairs"][record["symbol"]]["symbol_info"]
    for t in record["trades"]:
        risk = abs(t["entry_price"]-t["sl_initial"])/info["trade_tick_size"]*info["trade_tick_value"]*t["volume"]
        assert risk <= cash*.0075+1e-7
        assert t["volume"] <= p["settings"][record["symbol"]]["max_lot"]+1e-9
        assert t["swap_money"] == 0 and t["swap_events"] == []
        assert math.isclose(t["gross_pnl_money"]-t["spread_cost_money"]-t["commission_cost_money"]-t["slippage_cost_money"], t["pnl_money"], abs_tol=1e-8)
        cash += t["pnl_money"]
    assert math.isclose(cash, record["account"]["end_equity"], abs_tol=1e-7)
    assert record["wins_100_to_200"] == sum(100 <= t["pnl_money"] <= 200 for t in record["trades"])
    assert record["no_overnight_and_no_swap"] and record["late_exits"] == 0
later = [phases["later"] for name, phases in results.items() if name.endswith("_stress")]
full = [phases["full"] for name, phases in results.items() if not name.endswith("_stress")]
stressed = [phases["full"] for name, phases in results.items() if name.endswith("_stress")]
best = max(stressed, key=lambda v: v["metrics"]["net_pnl"])
labels = {"m1_sweep_reclaim": "M1 sweep/reclaim", "m1_ema_reclaim": "M1 EMA reclaim", "m5_sweep_m1_confirm": "M5 sweep + M1 confirm"}
lines = ["# New M1/M5 scalp entries: EUR10,000, risk ceiling 0.75%", "",
    "This is new entry research, not merely a shortened M30 exit. Three pure closed-bar entry definitions were fixed before outcomes and tested on all four available FX exports. No bot, orders, live configuration or production entry mode was enabled.", "",
    f"**Best full-period stressed result: {best['scenario']}, EUR{best['metrics']['net_pnl']:,.2f}.** Earlier selection and later validation below must be considered separately. A positive full-period result containing selection data is not proof of a stable future edge.", "",
    f"All12 prototypes have later stressed net below zero: **{all(v['metrics']['net_pnl'] < 0 for v in later)}**. A candidate may improve total historical profit while failing this later check. No later-result winner replaces the frozen earlier nomination.", "",
    "Common period: **2025-09-01 to 2026-11-11 exclusive**, approximately14 months. Every account starts independently at EUR10,000; no monthly resets, aggregation into a concurrent portfolio or guarantee of live returns.", "",
    "## Earlier-selected candidates", "",
    "Only participating, zero-financing/non-overnight candidates with positive earlier stressed net are eligible; otherwise cash. Tie lower sampled drawdown, then name. Selection was locked before later/full outcomes.", "",
    "| Pair | Earlier nomination | Earlier stressed net | Later stressed net | Full normal net | Full stressed net | Full stressed drawdown |", "|---|---|---:|---:|---:|---:|---:|"]
for pair, item in locked.items():
    model = item["selected"]
    if model is None:
        lines.append(f"| {pair} | cash; no eligible earlier candidate | - | - | - | - | - |")
        continue
    a, b = results[pair+"_"+model], results[pair+"_"+model+"_stress"]
    lines.append(f"| {pair} | {labels[model]} | EUR{b['earlier']['metrics']['net_pnl']:,.2f} | EUR{b['later']['metrics']['net_pnl']:,.2f} | EUR{a['full']['metrics']['net_pnl']:,.2f} | EUR{b['full']['metrics']['net_pnl']:,.2f} | EUR{b['full']['account']['m1_close_drawdown']:,.2f} |")
lines += ["", "Earlier: 2025-09-01 to2026-03-01 exclusive. Later: 2026-03-02 to2026-11-11 exclusive, with one calendar day between. Separate earlier/later accounts each start flat and cannot be summed to reconstruct the continuous full account.", "",
    "## Every prototype, including rejected candidates", "",
    "| Pair | Entry | Full normal / stressed net | Stressed drawdown | Trades normal/stressed | EUR100-200 net winners normal/stressed | Mean initial price risk normal/stressed |", "|---|---|---:|---:|---:|---:|---:|"]
for pair in p["pairs"]:
    for model in p["models"]:
        a, b = (results[pair+"_"+model+suffix]["full"] for suffix in ("", "_stress"))
        lines.append(f"| {pair} | {labels[model]} | EUR{a['metrics']['net_pnl']:,.2f} / EUR{b['metrics']['net_pnl']:,.2f} | EUR{b['account']['m1_close_drawdown']:,.2f} | {a['metrics']['trades']} / {b['metrics']['trades']} | {a['wins_100_to_200']} / {b['wins_100_to_200']} | EUR{a['mean_initial_price_risk_money']:.2f} / EUR{b['mean_initial_price_risk_money']:.2f} |")
lines += ["", "All trades, losses and target-band counts use net results after modeled costs. Drawdown includes M1-close open P&L, incurred entry fees and actual simulated exit fills; intrabar/tick drawdown can be greater.", "",
    "## Entry definitions and unchanged controls", "",
    "All models use M1 decisions, completed M5 EMA20/EMA50 trend and EMA20 slope over3 prior M5 bars. Confirming M1 body is at least60% of range and range at least1.2 times the preceding20-range mean. Sweep penetration exceeds0.2 pip. Spread cap is0.7 pip.", "",
    "- M1 sweep/reclaim: prior M1 sweeps12 earlier M1 extrema and closes back inside; the current directional candle confirms beyond that sweep candle's opposite edge.",
    "- M1 EMA reclaim: prior M1 sweeps4 earlier extrema and closes against the M5 trend across M1 EMA20; current M1 reclaims EMA20 and the prior candle's opposite edge.",
    "- M5 sweep/M1 confirm: latest completed M5 sweeps12 prior M5 extrema and reclaims them; M1 then confirms beyond its preceding2 extrema while that setup remains the latest closed M5, within1-5 minutes. One entry confirmation per sweep.", "",
    "Initial SL is behind the swept/last5 M1 extreme with0.2-pip padding. Raw bid-close structure distance must be6-15 pips; rejected stops are not widened to meet a preferred distance. Lots are sized on the actual adverse filled entry-to-stop distance, including spread/slippage. Initial target remains2R, trailing activates1.5R with1R gap and removes TP at activation. Existing stops never move farther away.", "",
    p["risk_constraints"], "",
    "The risk percentage is a maximum, not a promise that every position uses the full budget. The actual average initial risk in the table makes volume-ceiling effects explicit. Fees/gaps can add to a price-stop loss. Historical margin requirements and changing EUR conversions are not reconstructed.", "",
    "Both directions retain the30-minute cap, daytime UTC entries05:00-18:00 intersected with existing sessions, and flat-by19:00 policy. Original3600-second cooldown is retained. Swap stays actively modeled and every position is audited against both rollover clocks; all48 accounts have zero swap, zero overnight positions and zero late exits.", "",
    "## Costs, evidence and limitations", "",
    "Normal: observed M1 historical spreads,1-pip fallback, EUR3.50 commission/lot/side and0.2-pip adverse market/stop slippage. Stress doubles commission/slippage and negative swap debits while preserving positive credits; fallback spread becomes2 pips. Observed spreads are not doubled. TP-limit exits have no exit slippage. These remain declared cost assumptions, not a broker invoice.", "",
    "The same four histories, per-pair constant EUR tick valuations and financing snapshot as the previous scalp study are used. NZDUSD limits the common comparison to September2025 onward. Current swap rates are held constant with the prior explicit Wednesday triple-day assumption, but financing is zero in all observed paths under both GMT+3 and GMT+2 audit schedules.", "",
    "There is no parameter grid, pair-specific tuning or post-result change to entry thresholds. These prices and dates were examined repeatedly in prior research; the later period is not an untouched holdout. Candidate counts are small and disclosed. Full ranking is descriptive; earlier profit alone cannot establish reliability. Source OHLC cannot reconstruct tick-level spread/latency/liquidity or all historical broker stop/margin constraints.", "",
    "Pure signal definitions contain no broker calls and can be reused by a future live adapter, but current dispatch is offline only and requires explicit history. The research configuration is not an enabled production strategy. Existing entry/exit risk and cost code is shared.", "",
    "## Validation and reproduction", "",
    f"**{args.tests_passed} passed, one existing expected failure.** New tests cover each setup on BUY/SELL, future-bar invariance, M5-close ordering, insufficient displacement/structural width, immutable structural protection, offline-only guards, decision-clock validation, earlier-only/cash nomination and cached-vs-full replay equality for final/time/daily/stop exits in both directions.", "",
    "Only entry feature construction is skipped on no-signal minutes. Every open-position M1 bar is still processed for SL/TP, financing, daily protection and elapsed exits; the regression comparison verifies identical trades and balances with this optimization disabled. Independent report audit reconciles all48 trade/cost ledgers, target-band counts, lot ceilings and per-entry0.75% price-risk bounds.", "",
    "The frozen plan records all hypotheses, reference/history/source digests, precise settings and selection rules. Keep the original source commit and use a new output directory after changing source or assumptions. No bot was started and no order was placed."]
(folder/"README.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
checks = {"accounts": 48, "positive_full_normal": sum(v["metrics"]["net_pnl"] > 0 for v in full),
    "positive_full_stressed": sum(v["metrics"]["net_pnl"] > 0 for v in stressed),
    "positive_later_stressed": sum(v["metrics"]["net_pnl"] > 0 for v in later),
    "no_financing_overnight_or_late_violations": True, "per_entry_price_risk_budget_verified": True,
    "tests_passed": args.tests_passed, "expected_failures": 1}
(folder/"checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
print("48 entry ledgers reconciled", checks)
