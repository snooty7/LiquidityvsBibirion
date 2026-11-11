"""Offline, preregistered USDCHF M30 improvement study. Never connects to MT5."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import HistoricalData, load_history
from src.services.config import AppConfig, SymbolConfig
from src.tools.backtest_mt5 import ClosedTrade, run_backtest
from src.tools.walk_forward import (
    RISK_KEYS, default_config_paths, discover_branches, history_coverage,
    make_folds, trade_metrics,
)


@dataclass(frozen=True)
class Candidate:
    name: str
    settings: SymbolConfig
    hypothesis: str


def candidates(base: SymbolConfig) -> list[Candidate]:
    """Freeze eight hypotheses; sizing, exposure limits and initial stops stay constant."""
    definitions = [
        ("baseline", {}, "Configured M5 confirmation with the original 1R/1R trailing exit"),
        ("trail_later_1_5", {"trailing_activation_r": 1.5}, "Let an M30 trade develop before trailing"),
        ("trail_later_2", {"trailing_activation_r": 2.0}, "Delay trailing until a larger favorable move"),
        ("trail_wider_1_5", {"trailing_activation_r": 1.5, "trailing_gap_r": 1.5}, "Allow wider post-activation fluctuations"),
        ("fixed_2r", {"trailing_stop_mode": "off"}, "Keep the original fixed 2R target without trailing"),
        ("fixed_1_5r", {"trailing_stop_mode": "off", "rr": 1.5}, "Test a closer fixed target"),
        ("fresh_confirmation", {"confirm_expiry_bars": 3}, "Reject confirmations that arrive late after the sweep"),
        ("stronger_displacement", {"confirmation_displacement_range_multiple": 2.0}, "Require a stronger confirming impulse"),
    ]
    return [Candidate(name, replace(base, **changes), hypothesis) for name, changes, hypothesis in definitions]


def training_score(metrics: dict) -> float:
    """Penalize realized drawdown rather than select on net profit alone."""
    return metrics["net_pnl"] - 0.5 * metrics["max_realized_drawdown"]


def select_training(metrics: dict[str, dict], *, min_trades: int = 20) -> str:
    """Only prior training metrics may influence this fold's selection."""
    base = metrics["baseline"]
    eligible = [(name, values) for name, values in metrics.items()
                if name != "baseline" and values["trades"] >= min_trades and values["net_pnl"] > 0
                and values["max_realized_drawdown"] <= 1.25 * base["max_realized_drawdown"]
                and training_score(values) > training_score(base)]
    eligible.sort(key=lambda item: (-training_score(item[1]), item[0]))
    return eligible[0][0] if eligible else "baseline"


def select_fixed(training: dict[int, dict[str, dict]], development_folds: int = 9) -> str:
    """Choose once from development training windows, before any new test replay."""
    windows = [training[index] for index in range(1, development_folds + 1)]
    base_score = sum(training_score(window["baseline"]) for window in windows)
    base_dd = sum(window["baseline"]["max_realized_drawdown"] for window in windows)
    eligible = []
    for name in windows[0]:
        if name == "baseline":
            continue
        values = [window[name] for window in windows]
        score = sum(training_score(value) for value in values)
        if (sum(value["trades"] >= 20 for value in values) >= 6
                and sum(value["net_pnl"] for value in values) > 0
                and sum(value["max_realized_drawdown"] for value in values) <= 1.25*base_dd
                and score > base_score):
            eligible.append((name, score))
    return sorted(eligible, key=lambda item: (-item[1], item[0]))[0][0] if eligible else "baseline"


def promotion_checks(base: dict, candidate: dict, base_holdout: dict, candidate_holdout: dict,
                     base_stress: dict, candidate_stress: dict, name: str) -> dict[str, bool]:
    """All declared gates must pass; a holdout loss cannot be relabeled a success."""
    return {
        "alternative_selected_from_training": name != "baseline",
        "aggregate_net_improved": candidate["net_pnl"] > base["net_pnl"],
        "aggregate_drawdown_controlled": candidate["max_realized_drawdown"] <= 1.25*base["max_realized_drawdown"],
        "holdout_net_positive_and_improved": candidate_holdout["net_pnl"] > max(0, base_holdout["net_pnl"]),
        "holdout_minimum_20_trades": candidate_holdout["trades"] >= 20,
        "holdout_drawdown_controlled": candidate_holdout["max_realized_drawdown"] <= 1.25*base_holdout["max_realized_drawdown"],
        "stress_net_positive_and_not_worse": candidate_stress["net_pnl"] > 0 and candidate_stress["net_pnl"] >= base_stress["net_pnl"],
    }


_history: HistoricalData | None = None


def _forbid_broker() -> None:
    from src.execution import mt5_adapter
    def forbidden(*args, **kwargs):
        raise RuntimeError("This offline study forbids broker connections and trading")
    for name in ("initialize", "send_market_order_with_price_protection", "send_market_order_with_fallback",
                 "close_position_market_with_fallback", "modify_position_protection"):
        setattr(mt5_adapter.MT5Adapter, name, forbidden)
    if mt5_adapter.mt5 is not None:
        mt5_adapter.mt5.initialize = forbidden
        mt5_adapter.mt5.order_send = forbidden
        mt5_adapter.mt5.order_check = forbidden


def _initialize_worker(history_path: str) -> None:
    global _history
    _forbid_broker()
    _history = load_history(Path(history_path))["USDCHF"]


def _replay(task: tuple) -> tuple[str, dict]:
    key, app, cfg, start, end, costs, cache = task
    path = Path(cache)/(key+".json")
    if path.exists():
        return key, json.loads(path.read_text())
    assert _history is not None
    reason = history_coverage(_history, cfg, start, end, max_gap_days=4)
    if reason:
        raise ValueError(reason)
    _, trades = run_backtest(app, cfg, start, end, initial_equity=10000, costs=costs,
                             history=_history, end_exclusive=True)
    for trade in trades:
        if not start <= datetime.fromisoformat(trade.entry_time_utc) < end:
            raise ValueError("Out-of-window entry")
        if not datetime.fromisoformat(trade.entry_time_utc) <= datetime.fromisoformat(trade.exit_time_utc) <= end:
            raise ValueError("Out-of-window outcome")
    result = {"metrics": trade_metrics(trades, 10000), "trades": [asdict(t) for t in trades]}
    path.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
    return key, result


def run_study(history_path: Path, output: Path, workers: int = 6) -> dict:
    """Register the protocol, run training, lock selections, then evaluate tests and stress."""
    _forbid_broker()
    source = next(branch for branch in discover_branches(default_config_paths())
                  if branch.branch_id == "92024-USDCHF-M30-3c27c3d9")
    variants = candidates(source.symbol)
    app = source.config
    folds = make_folds(datetime(2025, 8, 17, tzinfo=timezone.utc),
                       datetime(2026, 11, 11, tzinfo=timezone.utc), 90, 30, 1)
    base_costs, stress_costs = ExecutionCosts(), ExecutionCosts("historical", 2.0, 7.0, .4)
    history = load_history(history_path)["USDCHF"]
    history_hash = history.digest()
    del history
    code_hash = hashlib.sha256(b"".join(path.read_bytes() for folder in (
        "src/strategy", "src/risk", "src/backtesting", "src/engine"
    ) for path in sorted(Path(folder).glob("*.py"))) + Path("src/tools/backtest_mt5.py").read_bytes()
        + Path(__file__).read_bytes()).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    cache = history_path.parent/"usdchf_m30_research_cache"
    cache.mkdir(exist_ok=True)
    plan = {
        "registered_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_branch": source.branch_id, "source_configs": source.sources,
        "history_sha256": history_hash, "replay_code_sha256": code_hash,
        "costs": asdict(base_costs), "stress_costs": asdict(stress_costs),
        "variants": [{"name": v.name, "hypothesis": v.hypothesis, "settings": asdict(v.settings)} for v in variants],
        "folds": [fold.record() for fold in folds], "development_folds": 9, "confirmation_folds": [10, 11, 12],
        "selection_rule": "training net minus 0.5 realized drawdown; minimum 20 trades; drawdown <=1.25 baseline; positive net; otherwise baseline",
        "fixed_rule": "aggregate development-training score; at least six of nine windows with >=20 trades; positive aggregate net; aggregate drawdown sum <=1.25 baseline",
        "promotion_rule": "fixed candidate must improve aggregate and positive holdout net, maintain drawdown <=1.25 baseline, have >=20 holdout trades and remain positive/not worse under doubled assumed costs",
        "caveat": "These dates and baseline were previously examined. Confirmation folds are reserved within this study, not genuinely new unseen market data.",
        "broker_connections": False, "trading_calls": False,
    }
    (output/"plan.json").write_text(json.dumps(plan, indent=2, allow_nan=False), encoding="utf-8")
    print("Registered eight hypotheses; training first", flush=True)
    results = {}
    def task(name: str, fold, phase: str, costs: ExecutionCosts) -> tuple:
        cfg = next(v.settings for v in variants if v.name == name)
        start, end = ((fold.train_start, fold.train_end) if phase == "train" else (fold.test_start, fold.test_end))
        payload = [asdict(cfg), {key:getattr(app.runtime,key) for key in RISK_KEYS},
                   start.isoformat(), end.isoformat(), asdict(costs), history_hash, code_hash]
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return key, app, cfg, start, end, costs, str(cache)
    def batch(tasks: list[tuple], pool, label: str) -> None:
        unique = {item[0]:item for item in tasks if item[0] not in results}
        futures = [pool.submit(_replay, item) for item in unique.values()]
        for index, future in enumerate(as_completed(futures), 1):
            key, record = future.result()
            results[key] = record
            print(f"{label}: {index}/{len(futures)}", flush=True)
    with ProcessPoolExecutor(max_workers=workers, initializer=_initialize_worker,
                             initargs=(str(history_path),)) as pool:
        batch([task(v.name, f, "train", base_costs) for f in folds for v in variants], pool, "training")
        training = {f.index:{v.name:results[task(v.name,f,"train",base_costs)[0]]["metrics"] for v in variants} for f in folds}
        adaptive = {f.index:select_training(training[f.index]) for f in folds}
        fixed = select_fixed(training)
        locked = {"fixed":fixed,"adaptive":adaptive,"training_metrics":training}
        (output/"locked_selections.json").write_text(json.dumps(locked,indent=2),encoding="utf-8")
        print("Selections locked before test replays; fixed candidate:",fixed,flush=True)
        batch([task(name,f,"test",base_costs) for f in folds
               for name in {"baseline",fixed,adaptive[f.index]}],pool,"test")
        batch([task(name,f,"test",stress_costs) for f in folds[-3:]
               for name in {"baseline",fixed}],pool,"stress confirmation")
    def metrics(names: dict[int,str], selected_folds, costs) -> dict:
        trades = [ClosedTrade(**trade) for f in selected_folds
                  for trade in results[task(names[f.index],f,"test",costs)[0]]["trades"]]
        return trade_metrics(trades,10000)
    baseline_names = {f.index:"baseline" for f in folds}
    fixed_names = {f.index:fixed for f in folds}
    aggregate = {"baseline":metrics(baseline_names,folds,base_costs),
                 "fixed":metrics(fixed_names,folds,base_costs),"adaptive":metrics(adaptive,folds,base_costs)}
    holdout = {"baseline":metrics(baseline_names,folds[-3:],base_costs),
               "fixed":metrics(fixed_names,folds[-3:],base_costs),"adaptive":metrics(adaptive,folds[-3:],base_costs)}
    stress = {"baseline":metrics(baseline_names,folds[-3:],stress_costs),
              "fixed":metrics(fixed_names,folds[-3:],stress_costs)}
    checks = promotion_checks(aggregate["baseline"],aggregate["fixed"],holdout["baseline"],
                              holdout["fixed"],stress["baseline"],stress["fixed"],fixed)
    per_fold = [{"fold":f.index,"test_start":f.test_start.isoformat(),"test_end_exclusive":f.test_end.isoformat(),
                 "fixed_candidate":fixed,"adaptive_candidate":adaptive[f.index],
                 **{label:results[task(name,f,"test",base_costs)[0]]["metrics"]
                    for label,name in [("baseline","baseline"),("fixed",fixed),("adaptive",adaptive[f.index])]} } for f in folds]
    report = {"plan":plan,"locked_selections":locked,"aggregate":aggregate,"confirmation":holdout,
              "stress_confirmation":stress,"promotion_checks":checks,"promotion_passed":all(checks.values()),
              "per_fold":per_fold,"unique_replays":len(results)}
    (output/"report.json").write_text(json.dumps(report,indent=2,allow_nan=False),encoding="utf-8")
    print("FINISHED",json.dumps({"fixed":fixed,"promotion_passed":report["promotion_passed"],"aggregate":aggregate,"holdout":holdout}),flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history",type=Path,required=True)
    parser.add_argument("--output",type=Path,default=Path("reports/usdchf_m30_improvement"))
    parser.add_argument("--workers",type=int,default=6)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    run_study(args.history,args.output,args.workers)


if __name__ == "__main__":
    main()
