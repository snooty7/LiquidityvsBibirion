"""Audit and render the matched old-path and separate new-entry half-percent studies."""
import json
import math
from pathlib import Path

root = Path(__file__).resolve().parent
legacy = json.loads((root/"legacy/report.json").read_text())
fast = json.loads((root/"fast_entries/report.json").read_text())
lock = json.loads((root/"fast_entries/locked_selection.json").read_text())
for group, expected in [(legacy, 24), (fast, 18)]:
    plan = group["plan"]
    assert plan["capital"] == 10000 and plan["risk_pct"] == .5
    assert plan["settings"]["risk_pct"] == plan["runtime"]["max_total_open_risk_pct"] == .5
    rows = [v for phases in group["results"].values() for v in phases.values()]
    assert len(rows) == expected
    info = plan["symbol_info"]
    for v in rows:
        cash = 10000.
        for t in v["trades"]:
            risk = abs(t["entry_price"]-t["sl_initial"])/info["trade_tick_size"]*info["trade_tick_value"]*t["volume"]
            assert risk <= cash*.005+1e-7
            assert t["volume"] <= min(plan["settings"]["max_lot"], info["volume_max"])+1e-9
            assert math.isclose(t["swap_money"], sum(e[1] for e in t["swap_events"]), abs_tol=1e-8)
            assert math.isclose(t["gross_pnl_money"]-t["spread_cost_money"]-t["commission_cost_money"]-t["slippage_cost_money"]+t["swap_money"], t["pnl_money"], abs_tol=1e-8)
            cash += t["pnl_money"]
        assert math.isclose(cash, v["account"]["end_equity"], abs_tol=1e-7)
        assert v["wins_100_to_200"] == sum(100 <= t["pnl_money"] <= 200 for t in v["trades"])
for key in ("capital", "risk_pct", "windows", "runtime", "history_digest", "costs", "stress_costs", "snapshot"):
    assert legacy["plan"][key] == fast["plan"][key]
assert all(v["no_overnight_and_no_swap"] and v["late_exits"] == 0
           for phases in fast["results"].values() for v in phases.values())

conditions = ["", "## Shared funding, data and cost assumptions", "",
    "Instrument USDCHF (broker USDCHF-). **EUR10,000 initial equity, risk ceiling0.5% of current simulated equity**, approximately EUR50 initial price-risk budget. Original trailing activation1.5R/gap1R and initial2R target retained. Fees and gaps can add to the price-stop loss.", "",
    "Full period: **2024-11-15 00:00 UTC to2026-11-11 00:00 UTC exclusive** (through10 November2026 inclusive). Earlier:2024-11-15 to2025-11-15 exclusive; later:2025-11-16 to2026-11-11 exclusive. Each window is an independent continuous account with no monthly reset. Earlier/later nets cannot be added to reproduce full compounding and position carry.", "",
    "Normal costs: observed historical spread,1-pip missing-spread fallback, EUR3.50/lot/side commission and0.2-pip adverse market/stop slippage. Stress: EUR7,0.4 pip and double negative swap debits; positive credits unchanged. Observed spreads are not doubled; missing-spread fallback becomes2 pips. No adverse exit slippage on TP-limit fills.", "",
    "Swap is actively modeled at rollover. The saved12-November2026 broker snapshot is held constant over history, using the historical EUR tick valuation. It is not a reconstruction of changing daily historical financing. Invalid MT5 triple-day code7 requires the explicit prior Wednesday-triple assumption. Primary broker midnight is fixed GMT+3, with GMT+2 sensitivity; historical DST/clock policy is unknown.", "",
    "Both groups retain0.5% aggregate exposure cap, EUR150 daily trigger, single-position rule and original cooldown. Drawdown includes open P&L at observed M1 closes, incurred entry fees, financing cash flows and simulated fills; intrabar/tick losses can be larger. Capital/risk are identical in both groups, but entry definitions and initial stop structures differ in the new-entry group.", "",
    "No martingale, averaging, grid or widening an already-tightened stop. Historical margin, latency, true tick spreads/liquidity, changing conversion rates and broker stop constraints are not reconstructed. Dates and prior outcomes were examined repeatedly; these are exploratory historical tests, not untouched holdout evidence or live profitability guarantees."]

out = ["# Matched old USDCHF paths: EUR10,000, risk0.5%, trailing1.5R", "",
    "Only one trading rule differs: original positions can remain overnight; the other path closes **SELL only** before rollover. BUY retains the original overnight behavior. Entry signals, capital, percentage risk, size ceiling, stop/target/trailing, sessions, cooldown and cost assumptions are otherwise identical.", "",
    "In the primary GMT+3 scenario, the original earns more under normal costs, but SELL pre-rollover flattening is the only positive path under stressed costs. This is a paired replay, not proportional scaling of an older EUR20,000 no-swap result.", "",
    "## Primary full-period comparison", "",
    "| Variant | Costs including swap | Net profit | Ending equity | Sampled equity drawdown | Net winners EUR100-200 / all trades | Signed net swap |", "|---|---|---:|---:|---:|---:|---:|"]
names = {"original": "Original M30/M1", "sell_flat": "SELL flat before rollover"}
for model, label in names.items():
    for stress in (False, True):
        v = legacy["results"][model+"_gmt3"+("_stress" if stress else "")]["full"]
        out.append(f"| {label} | {'Stressed' if stress else 'Normal'} | EUR{v['metrics']['net_pnl']:,.2f} | EUR{v['account']['end_equity']:,.2f} | EUR{v['account']['m1_close_drawdown']:,.2f} | {v['wins_100_to_200']} / {v['metrics']['trades']} | EUR{v['swap_net']:,.2f} |")
out += ["", "SELL flattening reduces normal net by EUR119.41 versus original, but improves stressed net by EUR340.89 and reduces stressed sampled drawdown by EUR148.23. These figures refer to GMT+3 only; both clocks are reported below. Financing differences need not equal net-profit differences because early exits, sizing and daily protection can change the trade path.", "",
    "## Clock sensitivity and separate windows", "",
    "| Variant | Broker clock | Earlier normal / stressed net | Later normal / stressed net | Full normal / stressed net | Full stressed drawdown |", "|---|---|---:|---:|---:|---:|"]
for model, label in names.items():
    for offset in (3, 2):
        pairs = []
        for phase in ("earlier", "later", "full"):
            values = [legacy["results"][f"{model}_gmt{offset}"+("_stress" if s else "")][phase]["metrics"]["net_pnl"] for s in (False, True)]
            pairs.append(" / ".join(f"EUR{x:,.2f}" for x in values))
        dd = legacy["results"][f"{model}_gmt{offset}_stress"]["full"]["account"]["m1_close_drawdown"]
        out.append(f"| {label} | GMT+{offset} | "+" | ".join(pairs)+f" | EUR{dd:,.2f} |")
out += ["", "The original is stressed-negative under both clocks. SELL flattening is stressed-positive under both clocks, but the remaining profit is modest. No clock was chosen retrospectively for better returns.", "",
    "SELL positions close at the first available M1 opening quote at/after23:55 broker time; SELL entries are blocked from that deadline until midnight. Missing quotes do not create a fictional earlier fill: any incurred financing is retained. BUY remains unchanged, so positive BUY swap can remain in this path. The existing0.5-lot ceiling is nonbinding at most old-model entries and risk still derives from the20-pip initial structure/protection."] + conditions
out += ["", "See [separate M1/M5 tests](../fast_entries/README.md). They are not part of this old-path ranking.", "",
    "Validation: all24 account/cost/financing ledgers and every0.5% entry-risk budget reconcile. The paired-task regression verifies that only the label and SELL overnight policy differ. No live settings changed, bot started or order placed."]
(root/"legacy/README.md").write_text("\n".join(out)+"\n", encoding="utf-8")

out = ["# Separate new M1/M5 USDCHF entries: EUR10,000, risk0.5%", "",
    "These new entry prototypes are evaluated separately from the old M30/M1 comparison. Definitions and thresholds are unchanged from the preceding new-entry research; funding and risk are now matched to the requested EUR10,000/0.5% and the same full two-year USDCHF history.", "",
    "**No candidate had positive earlier stressed performance with trading participation. The registered selection therefore chose cash.** All three prototypes were nevertheless replayed on later/full data and both cost levels; cash fallback is not used to conceal their losses.", "",
    "## Every prototype, full period", "",
    "| New entry | Normal net | Stressed net | Stressed sampled drawdown | Trades normal/stressed | Net winners EUR100-200 normal/stressed | Mean initial price risk normal/stressed |", "|---|---:|---:|---:|---:|---:|---:|"]
labels = {"m1_sweep_reclaim": "M1 sweep/reclaim", "m1_ema_reclaim": "M1 EMA reclaim", "m5_sweep_m1_confirm": "M5 sweep + M1 confirm"}
for model, label in labels.items():
    a, b = fast["results"][model]["full"], fast["results"][model+"_stress"]["full"]
    out.append(f"| {label} | EUR{a['metrics']['net_pnl']:,.2f} | EUR{b['metrics']['net_pnl']:,.2f} | EUR{b['account']['m1_close_drawdown']:,.2f} | {a['metrics']['trades']} / {b['metrics']['trades']} | {a['wins_100_to_200']} / {b['wins_100_to_200']} | EUR{a['mean_initial_price_risk_money']:.2f} / EUR{b['mean_initial_price_risk_money']:.2f} |")
out += ["", "## Earlier selection and later validation", "",
    "| Entry | Earlier normal / stressed net | Earlier executed trades | Earlier confirmed raw setups | Later normal / stressed net |", "|---|---:|---:|---:|---:|"]
for model, label in labels.items():
    a, b = fast["results"][model], fast["results"][model+"_stress"]
    out.append(f"| {label} | EUR{a['earlier']['metrics']['net_pnl']:,.2f} / EUR{b['earlier']['metrics']['net_pnl']:,.2f} | {b['earlier']['metrics']['trades']} | {b['earlier']['confirmed_signal_candidates']} | EUR{a['later']['metrics']['net_pnl']:,.2f} / EUR{b['later']['metrics']['net_pnl']:,.2f} |")
out += ["", "Zero earlier M5-sweep P&L means no executed trades in that window, not a demonstrated break-even strategy. Confirmed raw setups can still be rejected by the entry/risk/session/spread guards. No prototype is substituted after looking at later results.", "",
    "Pure signals use completed M1/M5 bars: M5 EMA20/50 direction and prior slope, liquidity sweeps/reclaims and directional M1 displacement. M1 bodies must be>=60% of their range; range>=1.2 times the preceding20 M1 mean. Sweep penetration>0.2 pip. Spread cap0.7 pip. Structural initial SL behind the swept/last5 M1 extreme with0.2-pip padding, accepting6-15 raw pips. Initial2R target, trailing1.5R/gap1R. Full0.5% risk sizing uses the recorded broker volume ceiling, not a fixed lot. Old-path sizing ceiling is different, so these remain separate prototype bundles.", "",
    "Both directions use the30-minute cap, weekday05:00-18:00 UTC entries intersecting original sessions, and flat by19:00 UTC. Financing remains active as an audit; all18 paths have zero swap, no overnight positions and no late exits under both rollover-clock audits. Existing SL/TP and daily protection have priority; no stop is widened."] + conditions
out += ["", "All18 ledgers and per-entry0.5% risk budgets reconcile. Pure signal definitions are broker independent; current dispatch is offline only. No production mode or live setting is enabled. Earlier-only nomination was locked before later/full new-entry outcomes.", "",
    "See [matched old paths](../legacy/README.md) for the original-versus-SELL comparison; these groups are not combined into a retrospective winner selection."]
(root/"fast_entries/README.md").write_text("\n".join(out)+"\n", encoding="utf-8")

out = ["# USDCHF: matched EUR10,000, risk0.5%, trailing1.5R", "",
    "Two frozen protocols: **24 matched old-path accounts** and **18 separate new-entry accounts**. Full period2024-11-15 to2026-11-11 exclusive. No monthly resets. All results include modeled spread, commission, slippage and financing.", "",
    "## Original versus SELL pre-rollover flattening", "",
    "Primary GMT+3 clock; read the clock/cost limitations in the full report.", "",
    "| Old entry path | Normal net | Stressed net | Stressed sampled drawdown | EUR100-200 net winners normal/stressed |", "|---|---:|---:|---:|---:|"]
for model, label in names.items():
    a, b = legacy["results"][model+"_gmt3"]["full"], legacy["results"][model+"_gmt3_stress"]["full"]
    out.append(f"| {label} | EUR{a['metrics']['net_pnl']:,.2f} | EUR{b['metrics']['net_pnl']:,.2f} | EUR{b['account']['m1_close_drawdown']:,.2f} | {a['wins_100_to_200']} / {b['wins_100_to_200']} |")
out += ["", "Original earns more under normal costs; SELL flattening preserves a small positive net under stress. Both clock assumptions agree on those stressed profitability signs. [Full matched comparison](legacy/README.md).", "",
    "## New entry tests remain separate", "",
    "All three new M1/M5 USDCHF prototypes lost money under normal and stressed full-period costs. No positive participating earlier candidate qualified; the frozen nomination is cash. [Full new-entry tests](fast_entries/README.md).", "",
    "The historical broker swap snapshot is held constant across the test. This is not actual daily historical financing. Stress doubles commission, slippage and negative swap debits; positive credits and observed historical spreads remain unchanged. Constant EUR valuation, reused dates, minute/tick limitations and unmodeled margin are disclosed in each report.", "",
    "**397 tests passed; one existing expected failure.** Four new cases verify matched funding/risk/trailing, paired-old-task equivalence and actual BUY/SELL entry risk nearEUR50 rather than the earlier0.75% budget. All42 independent ledgers, costs, swap cash flows, risk bounds and target-band counts reconcile.", "",
    "```powershell", "python -m src.tools.research_usdchf_risk05 --history history/mt5_20261111/USDCHF_extended.json --output reports/usdchf_10k_risk05 --workers 6", "```", "",
    "Plans were frozen before results. Source/history/snapshot metadata and all trade ledgers are retained under each group; use a new output directory after source/protocol changes. No bot was started, no orders were placed and no live settings were changed."]
(root/"README.md").write_text("\n".join(out)+"\n", encoding="utf-8")
checks = {"capital": 10000, "risk_pct": .5, "legacy_accounts": 24, "separate_new_accounts": 18,
    "shared_data_period_costs_and_runtime": True, "per_entry_risk_budget_verified": True,
    "original_stressed_positive_both_clocks": all(legacy["results"][f"original_gmt{o}_stress"]["full"]["metrics"]["net_pnl"] > 0 for o in (3, 2)),
    "sell_flat_stressed_positive_both_clocks": all(legacy["results"][f"sell_flat_gmt{o}_stress"]["full"]["metrics"]["net_pnl"] > 0 for o in (3, 2)),
    "new_entry_nomination": lock, "tests_passed": 397, "expected_failures": 1}
(root/"checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
print("Audited all42 half-percent accounts; separate reports built")
