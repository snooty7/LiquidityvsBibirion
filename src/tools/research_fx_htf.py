"""Offline H1/H4 trend-pullback and confirmed range-breakout study on three FX pairs."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import load_history
from src.services.config import AppConfig, SymbolConfig
from src.tools.backtest_mt5 import ClosedTrade, run_backtest
from src.tools.research_usdchf_m30 import _forbid_broker, promotion_checks, study_folds
from src.tools.research_usdchf_three_ideas import register, select_fixed, select_profit, source_hash
from src.tools.walk_forward import RISK_KEYS, default_config_paths, discover_branches, history_coverage, trade_metrics

SYMBOLS = ("EURUSD", "GBPUSD", "USDCHF")
MODELS = ("baseline", "htf_trend_pullback", "htf_range_retest")
PROTECTED = ("risk_pct", "min_lot", "max_lot", "sl_pips", "rr", "cooldown_sec", "one_position_per_symbol",
             "ignore_portfolio_cap", "max_spread_pips", "allowed_sessions_utc", "trailing_stop_mode",
             "trailing_activation_r", "trailing_gap_r", "trailing_remove_tp_on_activation")
_history = None


def models(base: SymbolConfig, symbol: str) -> dict[str, SymbolConfig]:
    """Keep common risk/exits; change only signal definitions and their required context."""
    baseline = replace(base, symbol=symbol, cisd_timeframe="M1", cisd_lookback_bars=300,
                       trade_side_filter="both", long_entry_filter_mode="off", long_entry_min_slope_atr=0)
    result = {"baseline": baseline}
    for mode in MODELS[1:]:
        result[mode] = replace(baseline, strategy_mode=mode, timeframe="H1", confirmation_mode="none",
                               use_order_block_filter=False, bias_timeframe="H4", bias_lookback_bars=150,
                               ema_fast_period=20, ema_slow_period=50)
    for cfg in result.values():
        if any(getattr(cfg, key) != getattr(baseline, key) for key in PROTECTED):
            raise ValueError("H1/H4 model changed protected risk/exits")
    return result


def replay_code_hash() -> str:
    return hashlib.sha256(source_hash().encode()+Path(__file__).read_bytes()).hexdigest()


def make_plan(history_dir: Path) -> tuple[dict, AppConfig, dict]:
    source = next(b for b in discover_branches(default_config_paths())
                  if b.branch_id == "92024-USDCHF-M30-3c27c3d9")
    configurations = {symbol: models(source.symbol, symbol) for symbol in SYMBOLS}
    manifest = {}
    for symbol in SYMBOLS:
        path = history_dir / (symbol+"_extended.json")
        history = load_history(path)[symbol]
        for cfg in configurations[symbol].values():
            for fold in study_folds(365):
                for start, end in ((fold.train_start, fold.train_end), (fold.test_start, fold.test_end)):
                    reason = history_coverage(history, cfg, start, end, max_gap_days=4)
                    if reason:
                        raise ValueError(f"{symbol}/{cfg.strategy_mode}/fold {fold.index}: {reason}")
        manifest[symbol] = {"path": str(path), "sha256": history.digest(),
                            "native_timeframes": {tf: len(history.rates[tf]) for tf in history._source_timeframes},
                            "symbol_info": asdict(history.symbol_info)}
        del history
    plan = {
        "registered_at_utc": datetime.now(timezone.utc).isoformat(), "study": "fx_htf_two_models",
        "hypotheses": {
            "htf_trend_pullback": "H4 EMA20 above/below EMA50 with EMA50 slope over three bars; aligned H1 EMA20/50, previous H1 close pulls back across EMA20, current directional >=50%-body candle reclaims EMA20 and breaks previous high/low by 0.3 pip.",
            "htf_range_retest": "Same H4 trend; previous H1 closes beyond the prior 20-bar range by 0.3 pip; current H1 retests that boundary and closes outside it with a directional >=50%-body candle. Range excludes breakout and confirmation bars.",
        },
        "baseline": "Common reference: original USDCHF M30/M1 liquidity model applied separately to each pair with identical risk settings; not the previously configured EURUSD/GBPUSD live branches.",
        "ema_context": "Fixed 150 closed H1/H4 bars (3*EMA50); no forming candles; H4 must close by H1 decision.",
        "settings": {s: {name: asdict(cfg) for name, cfg in items.items()} for s, items in configurations.items()},
        "risk_runtime": {key: getattr(source.config.runtime, key) for key in RISK_KEYS},
        "protected_fields": list(PROTECTED), "risk_unchanged": "0.1% planned risk, 20-pip initial stop, 0.05 maximum lot, 2R initial TP, original 1R/1R trailing, same daily loss/exposure/valuation guards, one position per symbol, one-hour cooldown and original entry sessions/spread cap. No risk override, averaging or stop widening.",
        "history": manifest, "replay_code_sha256": replay_code_hash(),
        "costs": asdict(ExecutionCosts()), "stress_costs": asdict(ExecutionCosts("historical", 2, 7, .4)),
        "folds": [f.record() for f in study_folds(365)], "development_folds": list(range(1, 7)),
        "confirmation_folds": list(range(7, 13)), "initial_equity_per_fold": 10000,
        "fixed_selection": "Per pair, highest net sum over first six TRAINING windows only; positive/improved sum vs common baseline, >=4 windows with >=20 trades, DD sum<=1.25 baseline; otherwise baseline. No parameter tuning.",
        "adaptive_selection": "Per pair and window: highest own prior-training net; >=20 trades, positive/improved vs baseline, DD<=1.25 baseline. Otherwise baseline.",
        "promotion": "Fixed training-nominated model must improve aggregate and positive confirmation net, retain >=20 confirmation trades, aggregate/confirmation DD<=1.25 baseline, and positive/not-worse stressed confirmation net. All gates mandatory.",
        "comparison": "Replay all nine declared pair/model combinations, rank descriptively by net. Do not sum independent accounts or use test winners to amend frozen choices.",
        "limitations": [
            "These dates and prior strategies were examined before. Outcomes for these two new models are evaluated after registration; the historical period is not genuinely untouched future data.",
            "Three independently simulated EUR 10,000 accounts per model; no combined portfolio/correlation or concurrent cross-symbol daily/exposure simulation. Returns cannot be added into a single-account return.",
            "Folds start flat monthly; no compounding. Training windows overlap; their sums are selection diagnostics. Drawdown is realized cash-flow drawdown, not intratrade equity drawdown.",
            "Commission and slippage are assumptions; historical symbol valuation is constant. Swap/overnight financing, latency and full tick paths are not modeled. Overnight-trade counts are disclosed; net is after modeled execution costs, not every possible broker charge.",
            "Monthly forced closes limit holding duration. Multiple comparisons and prior history reuse limit inference; no model is approved for real-money trading by descriptive profit alone.",
        ],
        "history_access": "EURUSD/GBPUSD extended read-only from an already-running connected MT5 terminal with AutoTrading disabled; USDCHF uses the prior read-only snapshot. No bot/order operations.",
        "replay_broker_connections": False, "trading_calls": False,
    }
    return plan, source.config, configurations


def _initialize(path: str, symbol: str) -> None:
    global _history
    _forbid_broker()
    _history = load_history(Path(path))[symbol]


def _replay(task: tuple) -> tuple[str, dict]:
    key, app, cfg, start, end, costs, cache = task
    path = Path(cache) / (key+".json")
    if path.exists():
        return key, json.loads(path.read_text(encoding="utf-8"))
    if _history is None or _history.symbol != cfg.symbol:
        raise ValueError("Worker has incorrect symbol history")
    reason = history_coverage(_history, cfg, start, end, max_gap_days=4)
    if reason:
        raise ValueError(reason)
    _, trades = run_backtest(app, cfg, start, end, initial_equity=10000, costs=costs,
                             history=_history, end_exclusive=True)
    for trade in trades:
        if not start <= datetime.fromisoformat(trade.entry_time_utc) < end:
            raise ValueError("Entry outside replay window")
        if not datetime.fromisoformat(trade.entry_time_utc) <= datetime.fromisoformat(trade.exit_time_utc) <= end:
            raise ValueError("Outcome outside replay window")
    record = {"metrics": trade_metrics(trades, 10000), "trades": [asdict(t) for t in trades]}
    path.write_text(json.dumps(record, allow_nan=False), encoding="utf-8")
    return key, record


def run(history_dir: Path, output: Path, workers: int = 4, register_only: bool = False) -> dict:
    _forbid_broker()
    plan, app, cfgs = make_plan(history_dir)
    plan = register(plan, output)
    if register_only:
        print("Registered two hypotheses / three pairs / common baseline; coverage passed", flush=True)
        return plan
    cache = history_dir / "fx_htf_cache"
    cache.mkdir(exist_ok=True)
    folds, records = study_folds(365), {}
    costs, stress = ExecutionCosts(**plan["costs"]), ExecutionCosts(**plan["stress_costs"])

    def task(symbol, name, fold, phase, scenario):
        cfg = cfgs[symbol][name]
        start, end = ((fold.train_start, fold.train_end) if phase == "train" else (fold.test_start, fold.test_end))
        payload = [asdict(cfg), plan["risk_runtime"], start.isoformat(), end.isoformat(), asdict(scenario),
                   plan["history"][symbol]["sha256"], plan["replay_code_sha256"]]
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return key, app, cfg, start, end, scenario, str(cache)

    def batch(symbol, items, label):
        unique = {item[0]: item for item in items if item[0] not in records}
        path = plan["history"][symbol]["path"]
        with ProcessPoolExecutor(max_workers=workers, initializer=_initialize, initargs=(path, symbol)) as pool:
            futures = [pool.submit(_replay, item) for item in unique.values()]
            for index, future in enumerate(as_completed(futures), 1):
                key, record = future.result()
                records[key] = record
                print(f"{symbol} {label}: {index}/{len(futures)}", flush=True)

    for symbol in SYMBOLS:
        batch(symbol, [task(symbol, name, f, "train", costs) for f in folds for name in MODELS], "training")
    locked, training = {}, {}
    for symbol in SYMBOLS:
        training[symbol] = {f.index: {name: records[task(symbol, name, f, "train", costs)[0]]["metrics"]
                                     for name in MODELS} for f in folds}
        fixed, diagnostics = select_fixed(training[symbol], list(MODELS[1:]))
        adaptive = {}
        for f in folds:
            name, reasons = select_profit(training[symbol][f.index], list(MODELS[1:]))
            adaptive[f.index] = {"selected": name, "rejections": reasons}
        locked[symbol] = {"fixed": fixed, "fixed_diagnostics": diagnostics, "adaptive": adaptive}
    (output / "locked_selections.json").write_text(json.dumps({"selections": locked, "training": training},
        indent=2, allow_nan=False), encoding="utf-8")
    print("Locked ALL pairs before ANY tests:", {s: d["fixed"] for s, d in locked.items()}, flush=True)
    for symbol in SYMBOLS:
        batch(symbol, [task(symbol, name, f, "test", scenario)
                       for windows, scenario in ((folds, costs), (folds[6:], stress))
                       for f in windows for name in MODELS], "test/stress")

    def summarize(symbol, choices, windows, scenario):
        trades = [ClosedTrade(**t) for f in windows
                  for t in records[task(symbol, choices[f.index], f, "test", scenario)[0]]["trades"]]
        return {"metrics": trade_metrics(trades, 10000),
                "overnight_trades": sum(t.exit_time_utc[:10] != t.entry_time_utc[:10] for t in trades),
                "sides": {side: trade_metrics([t for t in trades if t.side == side], 10000)
                          for side in ("BUY", "SELL")}}

    scopes = {"aggregate": (folds, costs), "confirmation": (folds[6:], costs),
              "stress_confirmation": (folds[6:], stress)}
    comparison, policies = {}, {}
    for symbol in SYMBOLS:
        comparison[symbol] = {name: {scope: summarize(symbol, {f.index: name for f in windows}, windows, scenario)
                                     for scope, (windows, scenario) in scopes.items()} for name in MODELS}
        choice = locked[symbol]
        fixed = comparison[symbol][choice["fixed"]]
        baseline = comparison[symbol]["baseline"]
        adaptive = {scope: summarize(symbol, {int(i): v["selected"] for i, v in choice["adaptive"].items()}, windows, scenario)
                    for scope, (windows, scenario) in scopes.items()}
        gates = promotion_checks(baseline["aggregate"]["metrics"], fixed["aggregate"]["metrics"],
            baseline["confirmation"]["metrics"], fixed["confirmation"]["metrics"],
            baseline["stress_confirmation"]["metrics"], fixed["stress_confirmation"]["metrics"], choice["fixed"])
        policies[symbol] = {"fixed_name": choice["fixed"], "fixed": fixed, "adaptive": adaptive,
                            "promotion_gates": gates, "promotion_passed": all(gates.values())}
    ranking = {scope: sorted([
        {"symbol": symbol, "model": name, "net_pnl": comparison[symbol][name][scope]["metrics"]["net_pnl"]}
        for symbol in SYMBOLS for name in MODELS], key=lambda r: (-r["net_pnl"], r["symbol"], r["model"]))
        for scope in scopes}
    rows, test_trades = [], []
    for symbol in SYMBOLS:
        for phase, label, windows, scenario in (("train", "base", folds, costs), ("test", "base", folds, costs),
                                                 ("test", "stress", folds[6:], stress)):
            for f in windows:
                for name in MODELS:
                    item = task(symbol, name, f, phase, scenario)
                    rows.append({"symbol": symbol, "name": name, "fold": f.index, "phase": phase,
                                 "scenario": label, "start": item[3].isoformat(), "end_exclusive": item[4].isoformat(),
                                 "cache_key": item[0], "metrics": records[item[0]]["metrics"]})
                    if phase == "test":
                        test_trades.extend({"name": name, "fold": f.index, "scenario": label, **trade}
                                           for trade in records[item[0]]["trades"])
    report = {"status": "completed", "plan": plan, "locked_selections": locked, "comparison": comparison,
              "policies": policies, "descriptive_ranking": ranking, "rows": rows, "unique_replays": len(records)}
    (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    (output / "test_trades.json").write_text(json.dumps(test_trades, indent=2, allow_nan=False), encoding="utf-8")
    print("FINISHED", json.dumps({"winners": {scope: ranks[0] for scope, ranks in ranking.items()},
                                  "promotion": {s: p["promotion_passed"] for s, p in policies.items()}}), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-dir", type=Path, default=Path("history/mt5_20261111"))
    parser.add_argument("--output", type=Path, default=Path("reports/fx_htf"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--register-only", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("Workers must be positive")
    run(args.history_dir, args.output, args.workers, args.register_only)


if __name__ == "__main__":
    main()
