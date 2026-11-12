"""Causal M1/M5 entry prototypes, independent earlier selection and cost stress."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import datetime
import hashlib
import json
from pathlib import Path

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import load_history
from src.backtesting.scalping import ScalpPolicy
from src.backtesting.swaps import SwapModel, rates_from_snapshot, weekday_weights
from src.risk.sizing import calc_position_risk_money, pip_size
from src.strategy.fast_scalp import MODELS, ScalpFeatures, ScalpSignalProvider
from src.tools import research_fx_scalping as fx
from src.tools.capture_fx_history_swaps import PAIRS
from src.tools.research_spread_resilience import configurations
from src.tools.research_usdchf_m30 import _forbid_broker
from src.tools.research_usdchf_three_ideas import register
from src.tools.walk_forward import RISK_KEYS, default_config_paths, discover_branches, history_coverage

_feature_symbol = None
_features = None
_signals = {}


def initialize(paths):
    """Load no terminal; cache one pair's causal features in each research process."""
    global _feature_symbol, _features, _signals
    fx.initialize(paths)
    _feature_symbol, _features, _signals = None, None, {}


def configurations_for_pair(base, pair):
    """Use M1 decisions/M5 context, retaining risk, position ceiling and daily guard."""
    return replace(base, symbol=pair, timeframe="M1", bars=120,
        strategy_mode="fast_scalp_research", confirmation_mode="none",
        bias_timeframe="M5", setup_timeframe="M5", bias_lookback_bars=120,
        setup_lookback_bars=120, cisd_lookback_bars=120,
        use_bias_filter=False, use_order_block_filter=False, max_spread_pips=.7)


def worker(task):
    """Inject only complete causal entries; share all existing replay risk/execution logic."""
    global _feature_symbol, _features, _signals
    pair, model, replay_task = task
    history = fx.history_for(pair)
    pip = pip_size(history.symbol_info.digits, history.symbol_info.point)
    if _feature_symbol != pair:
        _features = ScalpFeatures(history.bars("M1"), history.bars("M5"), pip)
        _feature_symbol, _signals = pair, {}
    start, end = (int(replay_task[i].timestamp()) for i in (4, 5))
    key = model, start, end
    if key not in _signals:
        _signals[key] = _features.signals(model, start, end)
    provider = ScalpSignalProvider(_signals[key])
    result = fx.worker((pair, replay_task+(provider,)))
    risk = [calc_position_risk_money(t["entry_price"], t["sl_initial"], t["volume"], history.symbol_info)
            for t in result["trades"]]
    result.update(model=model, confirmed_signal_candidates=len(provider.signals),
        mean_initial_price_risk_money=sum(risk)/len(risk) if risk else 0,
        max_initial_price_risk_money=max(risk, default=0),
        trades_at_lot_ceiling=sum(t["volume"] >= replay_task[3].max_lot-1e-9 for t in result["trades"]))
    return result


def nominate(records):
    """Hold cash if no earlier stressed, participating, no-overnight prototype is positive."""
    eligible = [n for n, v in records.items() if v["metrics"]["trades"] > 0
                and v["metrics"]["net_pnl"] > 0 and v["no_overnight_and_no_swap"]]
    ranking = sorted(eligible, key=lambda n: (-records[n]["metrics"]["net_pnl"],
        records[n]["account"]["m1_close_drawdown"], n))
    return (ranking[0] if ranking else None), ranking


def run(root, reference_path, output, workers=6):
    """Register three entry families, lock earlier nominations, disclose all alternatives."""
    _forbid_broker()
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    original = reference["plan"]
    source = next(b for b in discover_branches(default_config_paths()) if b.branch_id == "92024-USDCHF-M30-3c27c3d9")
    base = replace(configurations(source.symbol)["trail_later_1_5"], risk_pct=.75)
    app = replace(source.config, runtime=replace(source.config.runtime, max_total_open_risk_pct=.75))
    paths = {p: str((root/m["input_file"]).resolve()) for p, m in original["pairs"].items()}
    cfgs, swaps, metadata = {}, {}, {}
    for pair in PAIRS:
        history = load_history(Path(paths[pair]))[pair]
        if history.digest() != original["pairs"][pair]["history_digest"]:
            raise ValueError("History changed; use the same reference inputs")
        cfgs[pair] = configurations_for_pair(base, pair)
        for start, end in original["windows"].values():
            reason = history_coverage(history, cfgs[pair], datetime.fromisoformat(start), datetime.fromisoformat(end), max_gap_days=4)
            if reason:
                raise ValueError(f"{pair}: {reason}")
        buy, sell = rates_from_snapshot(original["snapshot"]["symbols"][pair], history.symbol_info,
                                        original["snapshot"]["account_currency"])
        swaps[pair] = SwapModel(buy, sell, "Etc/GMT-3", weekday_weights(original["snapshot"]["symbols"][pair], 3))
        metadata[pair] = original["pairs"][pair]
        del history
    plan = {"capital_per_account": 10000, "risk_pct": .75,
        "settings": {p: asdict(c) for p, c in cfgs.items()}, "runtime": {k: getattr(app.runtime, k) for k in RISK_KEYS},
        "pairs": metadata, "windows": original["windows"], "models": list(MODELS),
        "entry_rules": {"common": "M1 decision after its close; M5 EMA20 above/below EMA50 and EMA20 slope over3 prior M5 bars. Confirming M1 body>=60% of range; range>=1.2*mean of20 preceding M1 ranges. Sweep penetration>0.2 pip. Spread<=0.7 pip. Structure SL behind swept/last5 M1 extreme plus0.2 pip; accept only6-15 pip raw distances. No future/forming candles.",
            "m1_sweep_reclaim": "Previous M1 sweeps the12 preceding M1 extrema and closes back inside; current directional displacement closes beyond that sweep candle's opposite edge.",
            "m1_ema_reclaim": "Previous M1 sweeps4 preceding extrema and closes across M1 EMA20 against the M5 trend; current M1 reclaims EMA20 and breaks the previous candle's opposite edge.",
            "m5_sweep_m1_confirm": "Most recent CLOSED M5 sweeps12 preceding M5 extrema and closes back inside. A subsequent M1 closes beyond its previous2 M1 extrema within1-5 minutes after setup close; one confirmation per sweep."},
        "exits": "Original2R initial target, trailing activation1.5R/gap1R, target removal at activation. Both sides capped at30 elapsed minutes, weekday entries05:00-18:00 UTC intersecting existing sessions, flat by19:00 UTC. Missing quotes cannot fabricate an earlier fill; financing remains active as violation watchdog.",
        "risk_constraints": "Initial price-risk budget<=0.75%, original0.5-lot ceiling,0.75% aggregate exposure,EUR150 daily trigger and single-position rule. Original3600-second cooldown retained. Tight structural stops can use LESS than0.75% because lot ceiling is unchanged; actual utilization is disclosed. No widened existing stops or averaging/martingale.",
        "confirmation_adapter": "Pure prototype returns a fully confirmed entry and structural SL. Research mode confirmation=none avoids applying the old second confirmation; legacy H4 bias/order-block gates are replaced by the explicit M5 trend, sweep and structure definitions. Provider is forbidden without offline history. No live mode or configuration enabled.",
        "costs": original["costs"], "stress_costs": original["stress_costs"],
        "swaps": {p: asdict(s) for p, s in swaps.items()}, "snapshot": original["snapshot"],
        "selection": "For each pair nominate highest earlier stressed net among participating, zero-financing/non-overnight prototypes with positive earlier net; tie smaller sampled drawdown then name. Otherwise cash. Lock before later/full alternative outcomes. Run all12 models regardless of nomination. Full-period rankings are descriptive, not a replacement for earlier-only nomination.",
        "execution_optimization": "Precompute causal features/signals once per window; skip only entry feature construction on minutes without a signal. Still replay every open-position M1 bar for SL/TP, fees, daily loss and time exit. Cache-vs-full-path equivalence tested for final/time/daily/stop exits in both directions.",
        "reference_report_digest": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
        "code_digest": hashlib.sha256(b"".join(p.read_bytes() for p in sorted(Path("src").rglob("*.py")))).hexdigest(),
        "limitations": original["limitations"] + ["Existing prices/windows have been examined repeatedly; this is exploratory entry research, not untouched holdout evidence.",
            "All thresholds fixed before outcomes; no parameter grid, combined winner or pair-specific tuning. Earlier positive results alone cannot establish sample reliability; counts and all negative paths are disclosed.",
            "Old M30/M1 capped30-minute records are contextual historical controls, not a new replay. Entry family, structural stop and spread gate differ; this is a complete prototype comparison, not a single-parameter attribution.",
            "Pure entry definitions are broker-independent and reusable, but current wiring is offline-only; production execution integration is not enabled or claimed."]}
    output.mkdir(parents=True, exist_ok=True)
    register(plan, output)
    records = {}
    def save():
        (output/"results.partial.json").write_text(json.dumps({"plan": plan, "results": records}, indent=2, allow_nan=False), encoding="utf-8")
    def task(pair, model, phase, stress):
        cfg = cfgs[pair]
        start, end = (datetime.fromisoformat(v) for v in plan["windows"][phase])
        name = pair+"_"+model+("_stress" if stress else "")
        return pair, model, (name, phase, replace(app, symbols=(cfg,)), cfg, start, end,
            ExecutionCosts(**plan["stress_costs" if stress else "costs"]),
            replace(swaps[pair], debit_multiplier=2 if stress else 1), 10000, ScalpPolicy(30))
    def batch(jobs, pool):
        futures = [pool.submit(worker, t) for t in jobs]
        for index, future in enumerate(as_completed(futures), 1):
            result = future.result()
            records.setdefault(result["scenario"], {})[result["window"]] = result
            save()
            print(result["scenario"], result["window"], round(result["metrics"]["net_pnl"], 2),
                "trades", result["metrics"]["trades"], "no_swap", result["no_overnight_and_no_swap"],
                index, "/", len(jobs), flush=True)
    with ProcessPoolExecutor(max_workers=workers, initializer=initialize, initargs=(paths,)) as pool:
        batch([task(p, m, "earlier", True) for p in PAIRS for m in MODELS], pool)
        locked = {}
        for pair in PAIRS:
            selected, ranking = nominate({m: records[pair+"_"+m+"_stress"]["earlier"] for m in MODELS})
            locked[pair] = {"selected": selected, "positive_earlier_ranking": ranking,
                            "fallback": "cash" if selected is None else None}
        (output/"locked_selection.json").write_text(json.dumps(locked, indent=2), encoding="utf-8")
        print("LOCKED", json.dumps(locked), flush=True)
        batch([task(p, m, phase, stress) for p in PAIRS for m in MODELS
               for phase, stress in [("later", True), ("full", False), ("full", True)]], pool)
    (output/"results.partial.json").replace(output/"report.json")
    print("COMPLETED:48 causal entry replays", flush=True)
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-root", type=Path, required=True)
    parser.add_argument("--reference", type=Path, default=Path("reports/fx_intraday_scalping/report.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/fx_fast_entries"))
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("Positive worker count required")
    run(args.history_root, args.reference, args.output, args.workers)
