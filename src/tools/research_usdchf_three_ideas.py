"""Frozen, offline USDCHF M30/M1 comparison: direction, spread and tighter exits."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import load_history
from src.services.config import AppConfig, SymbolConfig
from src.tools.backtest_mt5 import ClosedTrade
from src.tools.research_usdchf_m30 import (
    _forbid_broker, _initialize_worker, _replay, promotion_checks, study_folds,
)
from src.tools.walk_forward import RISK_KEYS, default_config_paths, discover_branches, trade_metrics


@dataclass(frozen=True)
class Variant:
    name: str
    family: str
    settings: SymbolConfig
    hypothesis: str


def variants(base: SymbolConfig) -> list[Variant]:
    """Predeclare six isolated hypotheses; do not combine their settings after testing."""
    definitions = [
        ("baseline", "baseline", {}, "M30 sweep, M1 confirmation, both directions; original exits"),
        ("buy_only", "direction", {"trade_side_filter": "buy"}, "Replay only BUY setups"),
        ("sell_only", "direction", {"trade_side_filter": "sell"}, "Replay only SELL setups"),
        ("spread_1_2", "spread", {"max_spread_pips": 1.2}, "Reject entries above 1.2 pips observed spread"),
        ("spread_0_9", "spread", {"max_spread_pips": .9}, "Reject entries above 0.9 pips observed spread"),
        ("trail_gap_0_75", "exit", {"trailing_gap_r": .75}, "Keep 1R activation; tighten trailing gap to 0.75R"),
        ("trail_gap_0_5", "exit", {"trailing_gap_r": .5}, "Keep 1R activation; tighten trailing gap to 0.5R"),
    ]
    result = [Variant(name, family, replace(base, **changes), note)
              for name, family, changes, note in definitions]
    allowed = {"trade_side_filter", "max_spread_pips", "trailing_gap_r"}
    for v in result:
        changed = {key for key, value in asdict(base).items() if asdict(v.settings)[key] != value}
        if not changed <= allowed:
            raise ValueError("Candidate changed a protected setting")
        if v.settings.max_spread_pips > base.max_spread_pips:
            raise ValueError("Spread protection cannot be relaxed")
    return result


def select_profit(training: dict[str, dict], names: list[str]) -> tuple[str, dict]:
    """Choose highest training net profit with the existing sample and drawdown caps."""
    base = training["baseline"]
    eligible, reasons = [], {}
    for name in names:
        m = training[name]
        failed = []
        if m["trades"] < 20:
            failed.append("fewer than 20 training trades")
        if m["net_pnl"] <= max(0.0, base["net_pnl"]):
            failed.append("training net not positive and improved")
        if m["max_realized_drawdown"] > 1.25 * base["max_realized_drawdown"]:
            failed.append("training drawdown exceeds 1.25 baseline")
        reasons[name] = failed
        if not failed:
            eligible.append(name)
    eligible.sort(key=lambda name: (-training[name]["net_pnl"], training[name]["max_realized_drawdown"], name))
    return eligible[0] if eligible else "baseline", reasons


def select_fixed(training: dict[int, dict], names: list[str]) -> tuple[str, dict]:
    """Nominate once from the first six training windows, before confirmation outcomes."""
    windows = [training[index] for index in range(1, 7)]
    base_net = sum(w["baseline"]["net_pnl"] for w in windows)
    base_dd = sum(w["baseline"]["max_realized_drawdown"] for w in windows)
    eligible, diagnostics = [], {}
    for name in names:
        metrics = [w[name] for w in windows]
        net = sum(m["net_pnl"] for m in metrics)
        dd = sum(m["max_realized_drawdown"] for m in metrics)
        count = sum(m["trades"] >= 20 for m in metrics)
        failures = []
        if count < 4:
            failures.append("fewer than four development-training windows with 20 trades")
        if net <= max(0.0, base_net):
            failures.append("development-training net sum not positive and improved")
        if dd > 1.25 * base_dd:
            failures.append("development-training drawdown sum exceeds 1.25 baseline")
        diagnostics[name] = {"net_sum": net, "drawdown_sum": dd, "windows_with_20_trades": count,
                             "rejections": failures}
        if not failures:
            eligible.append(name)
    eligible.sort(key=lambda name: (-diagnostics[name]["net_sum"], diagnostics[name]["drawdown_sum"], name))
    return eligible[0] if eligible else "baseline", diagnostics


def source_hash() -> str:
    """Fingerprint all local code affecting replay, metrics, selection and costs."""
    paths = {p for folder in ("strategy", "risk", "backtesting", "engine", "execution", "persistence", "services")
             for p in Path("src", folder).glob("*.py")}
    paths.update(Path("src/tools", name) for name in (
        "backtest_mt5.py", "walk_forward.py", "research_usdchf_m30.py", Path(__file__).name,
    ))
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def make_plan(history_path: Path) -> tuple[dict, AppConfig, list[Variant]]:
    """Resolve the existing baseline and record the protocol before any outcomes."""
    source = next(b for b in discover_branches(default_config_paths())
                  if b.branch_id == "92024-USDCHF-M30-3c27c3d9")
    base = replace(source.symbol, cisd_timeframe="M1", cisd_lookback_bars=300,
                   long_entry_filter_mode="off", long_entry_min_slope_atr=0.0)
    models = variants(base)
    history = load_history(history_path)["USDCHF"]
    plan = {
        "registered_at_utc": datetime.now(timezone.utc).isoformat(),
        "study": "usdchf_three_ideas", "baseline_branch": source.branch_id,
        "objective": "maximize net profit after costs subject to unchanged sample/drawdown and runtime risk guards",
        "variants": [{"name": v.name, "family": v.family, "hypothesis": v.hypothesis,
                      "settings": asdict(v.settings)} for v in models],
        "folds": [f.record() for f in study_folds(365)], "development_folds": [1, 2, 3, 4, 5, 6],
        "confirmation_folds": [7, 8, 9, 10, 11, 12],
        "costs": asdict(ExecutionCosts()), "stress_costs": asdict(ExecutionCosts("historical", 2, 7, .4)),
        "history_sha256": history.digest(), "replay_code_sha256": source_hash(),
        "risk_runtime": {key: getattr(source.config.runtime, key) for key in RISK_KEYS},
        "initial_equity_per_fold": 10000,
        "fixed_selection": "Per family and overall, maximize total net summed over first six TRAINING windows; positive/improved sum, >=4 windows with >=20 trades, DD sum<=1.25 baseline. Otherwise baseline. Training windows overlap and sums are diagnostics only.",
        "adaptive_selection": "Per family and overall, maximize own preceding training net; >=20 trades, positive/improved net, DD<=1.25 baseline. Otherwise baseline.",
        "promotion": "Fixed TRAINING-nominated alternative only: improved aggregate net, positive/improved confirmation net, >=20 confirmation trades, aggregate/confirmation DD<=1.25 baseline, positive/not-worse stressed confirmation net.",
        "test_comparison": "Replay every predeclared model on every test fold and stressed confirmation; rank by net profit DESCRIPTIVELY. Never use this ranking to change frozen training nominations or promotion gates.",
        "engine_alignment": "Replay defaults to the configured trade_side_filter, matching live; previously the replay default silently allowed both sides. Explicit --side remains an intentional research override. Live/replay share a finite, nonnegative spread gate with 1e-9-pip arithmetic tolerance at the boundary. All models including baseline are rerun.",
        "unchanged_risk": "0.1% risk, 20-pip initial SL, max lot 0.05, sizing/valuation fail-closed, one position per symbol, daily loss/exposure guards; no wider stops. Exit hypotheses only tighten the trailing gap; activation remains 1R.",
        "no_combinations": True,
        "limitations": [
            "These USDCHF dates and baseline/side results were previously examined; this is exploratory research, not untouched future validation.",
            "A test-period winner can reflect chance and multiple comparisons. No live readiness is inferred.",
            "Folds reset flat at EUR 10,000; returns sum without compounding. Drawdown measures realized cash flow, not intratrade equity.",
            "Native bid OHLC and historical spreads; assumed commission/slippage, constant symbol valuation; no swaps, latency or full tick reconstruction.",
            "Direction-only variants replay the entire signal/capacity path; they are not post-hoc deletion of losing trades.",
        ],
        "broker_connections": False, "trading_calls": False,
    }
    return plan, source.config, models


def register(plan: dict, output: Path) -> dict:
    """Keep the original registration; refuse to silently change a frozen protocol."""
    output.mkdir(parents=True, exist_ok=True)
    path = output / "plan.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        scrub = lambda p: {k: v for k, v in p.items() if k != "registered_at_utc"}
        if scrub(existing) != scrub(plan):
            raise ValueError("Frozen study differs; use a new output directory and declare the amendment")
        return existing
    path.write_text(json.dumps(plan, indent=2, allow_nan=False), encoding="utf-8")
    return plan


def run(history_path: Path, output: Path, workers: int = 6, register_only: bool = False) -> dict:
    """Block the broker, train, lock nominations, then compare all declared hypotheses."""
    _forbid_broker()
    plan, app, models = make_plan(history_path)
    plan = register(plan, output)
    if register_only:
        print("Registered three families / six hypotheses plus baseline", flush=True)
        return plan
    cache = history_path.parent / "three_ideas_cache"
    cache.mkdir(exist_ok=True)
    by_name = {v.name: v for v in models}
    folds = study_folds(365)
    costs, stress = ExecutionCosts(**plan["costs"]), ExecutionCosts(**plan["stress_costs"])
    families = {family: [v.name for v in models if v.family == family]
                for family in ("direction", "spread", "exit")}
    families["overall"] = [v.name for v in models if v.name != "baseline"]
    records = {}

    def task(name, fold, phase, scenario):
        cfg = by_name[name].settings
        start, end = ((fold.train_start, fold.train_end) if phase == "train" else (fold.test_start, fold.test_end))
        payload = [asdict(cfg), plan["risk_runtime"], start.isoformat(), end.isoformat(), asdict(scenario),
                   plan["history_sha256"], plan["replay_code_sha256"]]
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return key, app, cfg, start, end, scenario, str(cache)

    def batch(items, pool, label):
        unique = {item[0]: item for item in items if item[0] not in records}
        futures = [pool.submit(_replay, item) for item in unique.values()]
        for index, future in enumerate(as_completed(futures), 1):
            key, record = future.result()
            records[key] = record
            print(f"{label}: {index}/{len(futures)}", flush=True)

    with ProcessPoolExecutor(max_workers=workers, initializer=_initialize_worker, initargs=(str(history_path),)) as pool:
        batch([task(v.name, f, "train", costs) for f in folds for v in models], pool, "training")
        training = {f.index: {v.name: records[task(v.name, f, "train", costs)[0]]["metrics"]
                              for v in models} for f in folds}
        locked = {}
        for family, names in families.items():
            fixed, reasons = select_fixed(training, names)
            adaptive = {}
            for f in folds:
                name, rejections = select_profit(training[f.index], names)
                adaptive[f.index] = {"selected": name, "rejections": rejections}
            locked[family] = {"fixed": fixed, "fixed_diagnostics": reasons, "adaptive": adaptive}
        (output / "locked_selections.json").write_text(json.dumps({"selections": locked, "training": training},
            indent=2, allow_nan=False), encoding="utf-8")
        print("Locked before tests:", {k: v["fixed"] for k, v in locked.items()}, flush=True)
        batch([task(v.name, f, "test", costs) for f in folds for v in models], pool, "test")
        batch([task(v.name, f, "test", stress) for f in folds[6:] for v in models], pool, "stress confirmation")

    def summary(choices, windows, scenario):
        trades = [ClosedTrade(**t) for f in windows
                  for t in records[task(choices[f.index], f, "test", scenario)[0]]["trades"]]
        return {"metrics": trade_metrics(trades, 10000),
                "sides": {side: trade_metrics([t for t in trades if t.side == side], 10000)
                          for side in ("BUY", "SELL")}}

    scopes = {"aggregate": (folds, costs), "confirmation": (folds[6:], costs),
              "stress_confirmation": (folds[6:], stress)}
    comparison = {v.name: {scope: summary({f.index: v.name for f in windows}, windows, scenario)
                          for scope, (windows, scenario) in scopes.items()} for v in models}
    policies = {}
    for family, choice in locked.items():
        fixed = comparison[choice["fixed"]]
        adaptive = {scope: summary({int(i): s["selected"] for i, s in choice["adaptive"].items()}, windows, scenario)
                    for scope, (windows, scenario) in scopes.items()}
        bm = comparison["baseline"]
        gates = promotion_checks(bm["aggregate"]["metrics"], fixed["aggregate"]["metrics"],
            bm["confirmation"]["metrics"], fixed["confirmation"]["metrics"],
            bm["stress_confirmation"]["metrics"], fixed["stress_confirmation"]["metrics"], choice["fixed"])
        policies[family] = {"fixed_name": choice["fixed"], "fixed": fixed, "adaptive": adaptive,
                            "promotion_gates": gates, "promotion_passed": all(gates.values())}
    ranking = {scope: sorted(comparison, key=lambda name: (
        -comparison[name][scope]["metrics"]["net_pnl"], name)) for scope in scopes}
    rows = [{"fold": f.index, "phase": phase, "scenario": scenario_name, "name": v.name,
             "start": (f.train_start if phase == "train" else f.test_start).isoformat(),
             "end_exclusive": (f.train_end if phase == "train" else f.test_end).isoformat(),
             "cache_key": task(v.name, f, phase, scenario)[0],
             "metrics": records[task(v.name, f, phase, scenario)[0]]["metrics"]}
            for phase, scenario_name, windows, scenario in (("train", "base", folds, costs),
                ("test", "base", folds, costs), ("test", "stress", folds[6:], stress))
            for f in windows for v in models]
    report = {"plan": plan, "locked_selections": locked, "comparison": comparison,
              "descriptive_ranking": ranking, "policies": policies, "rows": rows,
              "unique_replays": len(records), "status": "completed"}
    (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    # Include the exact test trades so reported costs and drawdowns are independently auditable.
    test_trades = [{"fold": f.index, "name": v.name, "scenario": label, **trade}
                   for windows, scenario, label in ((folds, costs, "base"), (folds[6:], stress, "stress"))
                   for f in windows for v in models
                   for trade in records[task(v.name, f, "test", scenario)[0]]["trades"]]
    (output / "test_trades.json").write_text(json.dumps(test_trades, indent=2, allow_nan=False), encoding="utf-8")
    print("FINISHED", json.dumps({"winners": {s: names[0] for s, names in ranking.items()},
                                  "promotion": {k: v["promotion_passed"] for k, v in policies.items()}}), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/usdchf_three_ideas"))
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--register-only", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("Workers must be positive")
    run(args.history, args.output, args.workers, args.register_only)


if __name__ == "__main__":
    main()
