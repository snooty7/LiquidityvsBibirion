"""Offline USDCHF sizing sensitivity with fixed lot, stop, daily and exposure caps."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import load_history
from src.risk.sizing import SymbolTradeInfo, calc_position_risk_money
from src.services.config import AppConfig, SymbolConfig
from src.tools.backtest_mt5 import ClosedTrade
from src.tools.research_usdchf_m30 import _forbid_broker, _initialize_worker, _replay, study_folds
from src.tools.research_usdchf_three_ideas import register, source_hash
from src.tools.walk_forward import RISK_KEYS, default_config_paths, discover_branches, history_coverage, trade_metrics

RISK_LEVELS = (.1, .2, .3, .5)
REFERENCES = ("baseline", "spread_0_9")


def variants(base: SymbolConfig) -> dict[str, SymbolConfig]:
    """Only change declared risk_pct and the previously tested tighter spread reference."""
    base = replace(base, cisd_timeframe="M1", cisd_lookback_bars=300,
                   long_entry_filter_mode="off", long_entry_min_slope_atr=0)
    return {f"{name}_risk_{risk:g}": replace(base, risk_pct=risk,
            max_spread_pips=.9 if name == "spread_0_9" else base.max_spread_pips)
            for name in REFERENCES for risk in RISK_LEVELS}


def loss_streaks(trades: list[ClosedTrade]) -> dict:
    """Report count and money separately; a zero-net trade ends a strict losing run."""
    count = longest = 0
    loss = worst = 0.0
    for trade in sorted(trades, key=lambda t: (t.exit_time_utc, t.entry_time_utc)):
        if trade.pnl_money < 0:
            count += 1
            loss -= trade.pnl_money
            longest, worst = max(longest, count), max(worst, loss)
        else:
            count, loss = 0, 0.0
    return {"max_consecutive_losses": longest, "worst_loss_streak_money": worst}


def record_metrics(trades: list[ClosedTrade], cfg: SymbolConfig, info: SymbolTradeInfo) -> dict:
    """Reconstruct entry equity in one replay, without confusing budget and capped risk."""
    equity, maximum_pct, maximum_money = 10000., 0., 0.
    previous_exit = ""
    for trade in sorted(trades, key=lambda t: t.entry_time_utc):
        if trade.entry_time_utc < previous_exit:
            raise ValueError("Overlapping positions violate the single-position study")
        if not 0 < trade.volume <= cfg.max_lot+1e-12:
            raise ValueError("Trade violates the unchanged lot cap")
        money = calc_position_risk_money(trade.entry_price, trade.sl_initial, trade.volume, info)
        if equity <= 0 or not math.isfinite(money):
            raise ValueError("Cannot reconstruct entry risk")
        pct = money/equity*100
        if pct > cfg.risk_pct+1e-8:
            raise ValueError("Initial stop risk exceeds declared budget")
        maximum_pct, maximum_money = max(maximum_pct, pct), max(maximum_money, money)
        equity += trade.pnl_money
        previous_exit = trade.exit_time_utc
    return {"metrics": trade_metrics(trades, 10000), "loss_streaks": loss_streaks(trades),
            "volumes": dict(sorted(Counter(f"{t.volume:g}" for t in trades).items())),
            "at_lot_cap": sum(math.isclose(t.volume, cfg.max_lot, abs_tol=1e-12) for t in trades),
            "max_initial_stop_risk_pct": maximum_pct, "max_initial_stop_risk_money": maximum_money}


def code_hash() -> str:
    return hashlib.sha256(source_hash().encode()+Path(__file__).read_bytes()).hexdigest()


def make_plan(history_path: Path) -> tuple[dict, AppConfig, dict]:
    source = next(b for b in discover_branches(default_config_paths())
                  if b.branch_id == "92024-USDCHF-M30-3c27c3d9")
    cfgs = variants(source.symbol)
    history = load_history(history_path)["USDCHF"]
    folds = study_folds(365)
    early_start, early_end = folds[0].train_start, folds[0].train_end
    for cfg in cfgs.values():
        for start, end in [(early_start, early_end)]+[(f.test_start, f.test_end) for f in folds]:
            reason = history_coverage(history, cfg, start, end, max_gap_days=4)
            if reason:
                raise ValueError(reason)
    plan = {
        "registered_at_utc": datetime.now(timezone.utc).isoformat(), "study": "usdchf_risk_sensitivity",
        "objective": "Measure changed profit, loss streaks, drawdown and actual capped exposure; not select a live risk level",
        "risk_levels_pct": list(RISK_LEVELS), "references": list(REFERENCES),
        "settings": {name: asdict(cfg) for name, cfg in cfgs.items()},
        "risk_runtime": {key: getattr(source.config.runtime, key) for key in RISK_KEYS},
        "unchanged": "Max lot 0.05, 20-pip initial stop, same 2R initial target and 1R/1R trailing, EUR 150 daily limit with closing, 0.5% portfolio risk cap, one position, sizing/valuation guards, sessions and cooldown. Only configured risk_pct changes within each reference.",
        "initial_equity_per_replay": 10000,
        "earlier_year": {"start": early_start.isoformat(), "end_exclusive": early_end.isoformat()},
        "folds": [f.record() for f in folds], "confirmation_folds": list(range(7, 13)),
        "costs": asdict(ExecutionCosts()), "stress_costs": asdict(ExecutionCosts("historical", 2, 7, .4)),
        "history_sha256": history.digest(), "symbol_info": asdict(history.symbol_info),
        "replay_code_sha256": code_hash(),
        "protocol": "Eight declared configurations; full earlier-year base/stress replays plus twelve monthly tests and later-six stress for every configuration. No linear P&L multiplication, parameter tuning, training nomination or live promotion.",
        "risk_measure": "Maximum initial entry-to-stop price risk reconstructed against each replay's entry equity. Excludes commission, stop slippage and gaps; it is not a maximum possible loss. Declared risk_pct can remain unused because max_lot binds.",
        "streak_measure": "Strict negative-net sequences, zero/nonnegative breaks the run. Counts and worst sequence cash loss reported separately. Aggregate monthly streaks join independent folds descriptively; per-fold streaks and drawdowns also retained.",
        "limitations": [
            "The two references were selected because their previously examined historical test results were positive. This is sizing sensitivity on reused history, not evidence of a new edge or unseen validation.",
            "The earlier year is one continuous replay, not overlapping training sums. It is reported separately and must not be hidden by the later positive test year.",
            "Monthly folds each restart flat at EUR 10,000. Summed returns and drawdown are descriptive, not a continuously compounded account or a guaranteed income.",
            "Historical spreads, assumed commissions/slippage, constant historical valuation. Swap/overnight financing, full tick paths and latency are not modeled. Changing only sizing preserves comparability with prior reference reports.",
            "Higher risk budgets do not improve entry expectancy; realized losses and drawdowns can grow. No lot cap, stop, daily or portfolio protection is relaxed.",
        ],
        "broker_connections": False, "trading_calls": False, "live_risk_level_selected": None,
    }
    return plan, source.config, cfgs


def run(history_path: Path, output: Path, workers: int = 6, register_only: bool = False) -> dict:
    _forbid_broker()
    plan, app, cfgs = make_plan(history_path)
    plan = register(plan, output)
    if register_only:
        print("Registered risk budgets; all lot/stop/daily/exposure protections unchanged", flush=True)
        return plan
    cache = history_path.parent / "risk_levels_cache"
    cache.mkdir(exist_ok=True)
    costs, stress = ExecutionCosts(**plan["costs"]), ExecutionCosts(**plan["stress_costs"])
    early_start, early_end = (datetime.fromisoformat(plan["earlier_year"][k]) for k in ("start", "end_exclusive"))
    folds, records, items = study_folds(365), {}, []

    def task(name, start, end, scenario):
        payload = [asdict(cfgs[name]), plan["risk_runtime"], start.isoformat(), end.isoformat(), asdict(scenario),
                   plan["history_sha256"], plan["replay_code_sha256"]]
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return key, app, cfgs[name], start, end, scenario, str(cache)

    for name in cfgs:
        for label, index, start, end, scenario in [
            ("earlier_base", 0, early_start, early_end, costs), ("earlier_stress", 0, early_start, early_end, stress),
            *[("test_base", f.index, f.test_start, f.test_end, costs) for f in folds],
            *[("test_stress", f.index, f.test_start, f.test_end, stress) for f in folds[6:]],
        ]:
            items.append((name, label, index, task(name, start, end, scenario)))
    with ProcessPoolExecutor(max_workers=workers, initializer=_initialize_worker, initargs=(str(history_path),)) as pool:
        futures = [pool.submit(_replay, item) for _, _, _, item in items]
        for index, future in enumerate(as_completed(futures), 1):
            key, record = future.result()
            records[key] = record
            print(f"replay: {index}/{len(futures)}", flush=True)
    info = SymbolTradeInfo(**plan["symbol_info"])
    def collect(name, label, indices=None):
        return [ClosedTrade(**trade) for n, l, i, item in items
                if n == name and l == label and (indices is None or i in indices)
                for trade in records[item[0]]["trades"]]
    comparison = {}
    for name, cfg in cfgs.items():
        comparison[name] = {}
        for scope, label, indices in (("earlier_year", "earlier_base", None),
            ("earlier_year_stress", "earlier_stress", None), ("test_year", "test_base", None),
            ("confirmation", "test_base", set(range(7, 13))), ("stress_confirmation", "test_stress", None)):
            trades = collect(name, label, indices)
            m = trade_metrics(trades, 10000)
            # Entry equity resets per month; entry-risk maxima must be taken from
            # individual replays, never reconstructed from summed monthly P&L.
            individual = [record_metrics([ClosedTrade(**t) for t in records[item[0]]["trades"]], cfg, info)
                          for n, l, i, item in items if n == name and l == label and (indices is None or i in indices)]
            comparison[name][scope] = {"metrics": m, "loss_streaks": loss_streaks(trades),
                "volumes": dict(sorted(Counter(f"{t.volume:g}" for t in trades).items())),
                "at_lot_cap": sum(r["at_lot_cap"] for r in individual),
                "max_initial_stop_risk_pct": max(r["max_initial_stop_risk_pct"] for r in individual),
                "max_initial_stop_risk_money": max(r["max_initial_stop_risk_money"] for r in individual)}
    rows = [{"name": name, "phase": label, "fold": index, "start": item[3].isoformat(),
             "end_exclusive": item[4].isoformat(), "cache_key": item[0],
             **record_metrics([ClosedTrade(**t) for t in records[item[0]]["trades"]], cfgs[name], info)}
            for name, label, index, item in items]
    trades = [{"name": name, "phase": label, "fold": index, **t}
              for name, label, index, item in items for t in records[item[0]]["trades"]]
    report = {"status": "completed", "plan": plan, "comparison": comparison, "rows": rows,
              "unique_replays": len(records), "live_settings_changed": False, "live_risk_level_selected": None}
    (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    (output / "trades.json").write_text(json.dumps(trades, indent=2, allow_nan=False), encoding="utf-8")
    print("FINISHED", json.dumps({name: {s: d["metrics"]["net_pnl"] for s, d in scopes.items()}
                                  for name, scopes in comparison.items()}), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, default=Path("history/mt5_20261111/USDCHF_extended.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/usdchf_risk_levels"))
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--register-only", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("Workers must be positive")
    run(args.history, args.output, args.workers, args.register_only)


if __name__ == "__main__":
    main()
