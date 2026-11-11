"""Continuous EUR20k strategy comparison, risk-based sizing fixed at 0.5% per entry."""
from __future__ import annotations

import argparse
import bisect
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from copy import copy, deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import load_history
from src.risk.sizing import calc_position_risk_money
from src.tools import backtest_mt5 as replay
from src.tools.research_capital_20k import outcomes, CAPITAL
from src.tools.research_usdchf_m30 import _forbid_broker, study_folds
from src.tools.research_usdchf_three_ideas import register, source_hash
from src.tools.walk_forward import RISK_KEYS, default_config_paths, discover_branches, history_coverage

NAMES = ("baseline", "atr_trailing", "atr_fixed2r", "unrestricted_entries")
_history = None


def configurations(base, broker_max_lot):
    """Reference versus volatility-scaled protection and explicitly relaxed paper entry guards."""
    base = replace(base, risk_pct=.5, max_lot=.5, cisd_timeframe="M1", cisd_lookback_bars=300)
    return {"baseline": base, "atr_trailing": replace(base, max_lot=broker_max_lot),
            "atr_fixed2r": replace(base, max_lot=broker_max_lot, trailing_stop_mode="off"),
            "unrestricted_entries": replace(base, max_lot=broker_max_lot, allowed_sessions_utc=(),
                                              max_spread_pips=sys.float_info.max)}


def closed_atr(history, timestamp, period=14):
    """Mean true range from 14 closed M30 candles plus their previous close; no future prices."""
    end = bisect.bisect_right(history.timestamps("M30"), timestamp-1800)
    if end < period+1:
        return None
    rows = history.bars("M30")[end-period-1:end]
    values = []
    for previous, current in zip(rows, rows[1:]):
        high, low, close = float(current["high"]), float(current["low"]), float(previous["close"])
        if not all(math.isfinite(v) and v > 0 for v in (high, low, close)) or high < low:
            return None
        values.append(max(high-low, abs(high-close), abs(low-close)))
    return sum(values)/period


@contextmanager
def atr_gate(history, enabled):
    """Set initial SL to 1.5 closed-bar ATR, then use the existing risk sizer.

    This changes protection only BEFORE opening a simulated position. Existing
    stops are never widened; initial R remains immutable for trailing/loss guards.
    """
    original = replay._build_entry_trade
    state = {"blocked": 0}
    def build(cfg, runtime, info, equity, side, timestamp, price, key, note, pending=None, **kwargs):
        if enabled:
            atr = closed_atr(history, timestamp)
            if atr is None or atr <= 0 or pending is None:
                state["blocked"] += 1
                return None
            pip = replay.MT5Adapter.pip_size(info)
            quote = price+(kwargs.get("spread_pips", 0)*pip if side == "BUY" else 0)
            pending = copy(pending)
            pending.context = deepcopy(getattr(pending, "context", None) or {})
            pending.context["risk"] = {"sl_price": quote-1.5*atr if side == "BUY" else quote+1.5*atr,
                                        "tp_r_multiple": cfg.rr}
        return original(cfg, runtime, info, equity, side, timestamp, price, key, note, pending, **kwargs)
    try:
        replay._build_entry_trade = build
        yield state
    finally:
        replay._build_entry_trade = original


def account_curve(trades, history, costs=None):
    """Continuous account equity at observed M1 closes, including open P&L and incurred entry fees.

    Exit-bar equity uses the actual simulated fill, not the bar close after that
    fill. This is a minute-close estimate; intrabar/tick drawdown can be greater.
    """
    cash = peak = minimum = CAPITAL
    drawdown = 0.
    count = 0
    info = history.symbol_info
    costs = costs or ExecutionCosts()
    pip = replay.MT5Adapter.pip_size(info)
    rows, times = history.bars("M1"), history.timestamps("M1")
    previous_exit = -1
    def mark(equity):
        nonlocal peak, minimum, drawdown, count
        peak, minimum = max(peak, equity), min(minimum, equity)
        drawdown = max(drawdown, peak-equity)
        count += 1
    for t in sorted(trades, key=lambda t: t.entry_time_utc):
        start, end = (int(datetime.fromisoformat(v).timestamp()) for v in (t.entry_time_utc, t.exit_time_utc))
        if start < previous_exit:
            raise ValueError("Account has overlapping positions")
        entry_fee = t.commission_cost_money/2
        mark(cash-entry_fee)
        before = bisect.bisect_right(times, start-60)-1
        if before >= 0:
            bar = rows[before]
            quote = costs.exit_quote(t.side, float(bar["close"]), costs.spread(bar, info), pip)
            move = quote-t.entry_price if t.side == "BUY" else t.entry_price-quote
            mark(cash-entry_fee+move/info.trade_tick_size*info.trade_tick_value*t.volume)
        a, b = bisect.bisect_left(times, start), bisect.bisect_left(times, end-60)
        for bar in rows[a:b]:
            # Mark only after entry and strictly before its exit timestamp.
            if not start < int(bar["time"])+60 < end:
                continue
            spread = costs.spread(bar, info)
            quote = costs.exit_quote(t.side, float(bar["close"]), spread, pip)
            move = quote-t.entry_price if t.side == "BUY" else t.entry_price-quote
            mark(cash-entry_fee+move/info.trade_tick_size*info.trade_tick_value*t.volume)
        cash += t.pnl_money
        mark(cash)
        previous_exit = end
    return {"start_equity": CAPITAL, "end_equity": cash, "minimum_sampled_equity": minimum,
            "peak_sampled_equity": peak, "m1_close_drawdown": drawdown, "observations": count}


def select_earlier(records):
    """Nominate highest older-period net; disclose sample/target/drawdown rather than hide results."""
    ranking = sorted(records, key=lambda n: (-records[n]["metrics"]["net_pnl"],
                                             records[n]["account"]["m1_close_drawdown"], n))
    return ranking[0], {"ranking_by_older_net": ranking}


def code_hash():
    return hashlib.sha256(source_hash().encode()+Path(__file__).read_bytes()
        +Path("src/tools/research_capital_20k.py").read_bytes()).hexdigest()


def initialize(path):
    global _history
    _forbid_broker()
    _history = load_history(Path(path))["USDCHF"]


def worker(task):
    name, phase, app, cfg, start, end, costs = task
    reason = history_coverage(_history, cfg, start, end, max_gap_days=4)
    if reason:
        raise ValueError(reason)
    with atr_gate(_history, name.startswith("atr_")) as state:
        _, trades = replay.run_backtest(app, cfg, start, end, initial_equity=CAPITAL, costs=costs,
                                        history=_history, end_exclusive=True)
    cash = CAPITAL
    for t in trades:
        if not start <= datetime.fromisoformat(t.entry_time_utc) < end or not (
                datetime.fromisoformat(t.entry_time_utc) <= datetime.fromisoformat(t.exit_time_utc) <= end):
            raise ValueError("Trade outside period")
        risk = calc_position_risk_money(t.entry_price, t.sl_initial, t.volume, _history.symbol_info)
        if risk > cash*cfg.risk_pct/100+1e-7 or t.volume > cfg.max_lot+1e-9:
            raise ValueError("Trade exceeded unchanged risk")
        if not math.isclose(t.gross_pnl_money-t.spread_cost_money-t.commission_cost_money-t.slippage_cost_money,
                            t.pnl_money, abs_tol=1e-8):
            raise ValueError("Cost reconciliation failed")
        cash += t.pnl_money
    account = account_curve(trades, _history, costs)
    if not math.isclose(account["end_equity"], CAPITAL+sum(t.pnl_money for t in trades), abs_tol=1e-7):
        raise ValueError("Continuous account does not reconcile")
    return {"name": name, "phase": phase, "start": start.isoformat(), "end_exclusive": end.isoformat(),
            **outcomes(trades), "account": account, "atr_blocked": state["blocked"],
            "trades": [asdict(t) for t in trades]}


def run(path, output, workers=4, register_only=False):
    _forbid_broker()
    source = next(b for b in discover_branches(default_config_paths()) if b.branch_id == "92024-USDCHF-M30-3c27c3d9")
    history = load_history(path)["USDCHF"]
    cfgs = configurations(source.symbol, history.symbol_info.volume_max)
    folds = study_folds(365)
    windows = {"earlier": (folds[0].train_start, folds[0].train_end),
               "later": (folds[0].test_start, folds[-1].test_end)}
    costs, stress = ExecutionCosts(), ExecutionCosts("historical", 2, 7, .4)
    plan = {"registered_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Reduce bad-period losses and equity drawdown while retaining EUR100-200 net winning trades",
        "hypotheses": {"baseline": "Original M30/M1 model, 20-pip initial SL and original R trailing",
            "atr_trailing": "Initial stop =1.5*mean true range of last 14 CLOSED M30 bars; original 2R TP and 1R trailing. Risk-derived size, broker max volume rather than inherited lot ceiling.",
            "atr_fixed2r": "Same ATR-scaled initial stop; fixed 2R target, no trailing. Existing position-risk loss guard retained.",
            "unrestricted_entries": "Original fixed stop/trailing; remove inherited session, spread and EUR150 daily-loss entry restrictions in PAPER ONLY. Spread and all other modeled execution costs still charged. Single-position and 0.5% exposure guard retained."},
        "settings": {n: asdict(c) for n, c in cfgs.items()},
        "risk_runtime": {k: getattr(source.config.runtime, k) for k in RISK_KEYS},
        "risk_fixed": "EUR20,000 start; 0.5% risk per entry, risk-derived lots, one position and 0.5% concurrent exposure cap. Never widen an already-open stop, average down or increase size after a loss. All changes are paper-only.",
        "runtime_changes": {"unrestricted_entries": {"daily_loss_limit_usd": 0}},
        "windows": {n: {"start": a.isoformat(), "end_exclusive": b.isoformat()} for n, (a, b) in windows.items()},
        "accounting": "Each period is ONE continuous account starting EUR20,000, without monthly resets. End equity includes all modeled costs. Equity drawdown uses open P&L at observed M1 closes, incurred entry commission and actual simulated exit fills; it excludes unknown intrabar/tick extremes and swap.",
        "selection": "Highest earlier base-cost net, tie lower M1-close equity drawdown. Lock before later results. No arbitrary sample gate hides a candidate; trade counts, EUR100-200 winners and drawdowns are disclosed for every model.",
        "evaluation": "Show earlier net/loss and drawdown, later net/drawdown, mean winners and count EUR100-200, plus doubled-cost outcomes. No live approval; positive results must be observed, not assumed.",
        "costs": asdict(costs), "stress_costs": asdict(stress), "history_sha256": history.digest(),
        "replay_code_sha256": code_hash(),
        "limitations": ["Earlier and later dates and baseline outcomes were previously examined; this is exploratory historical validation, not untouched forward evidence.",
            "A larger mean winner does not guarantee every successful trade reaches EUR100-200; trade counts and target-band counts are retained.",
            "Swap/financing excluded; commission/slippage assumptions and constant historical symbol valuation. No full tick/latency model.",
            "Broker volume maximum is honored; historical margin requirements and broker minimum stop-distance constraints are not reconstructed.",
            "M1-close equity drawdown can be smaller than intrabar drawdown. Daily guard is a trigger, not a guaranteed loss bound.",
            "The unrestricted paper scenario disables the daily guard and can incur larger daily losses; it does not alter the live protection. Research hooks are not enabled in live profiles.",
            "No tuning of the four hypotheses after outcomes. Both years were previously examined; no statistical confirmation is claimed."],
        "broker_connections": False, "trading_calls": False, "live_settings_changed": False}
    del history
    plan = register(plan, output)
    if register_only:
        print("Registered three strategy changes and baseline; continuous accounts, 0.5% risk", flush=True)
        return plan
    records = {}
    def task(name, phase):
        period = "earlier" if phase.startswith("earlier") else "later"
        a, b = windows[period]
        app = replace(source.config, runtime=replace(source.config.runtime, daily_loss_limit_usd=0)) if name == "unrestricted_entries" else source.config
        return name, phase, app, cfgs[name], a, b, stress if phase.endswith("stress") else costs
    def batch(tasks, pool):
        futures = [pool.submit(worker, t) for t in tasks]
        for index, future in enumerate(as_completed(futures), 1):
            r = future.result()
            records[(r["name"], r["phase"])] = r
            print(r["phase"], r["name"], f"{index}/{len(futures)}", flush=True)
    with ProcessPoolExecutor(max_workers=workers, initializer=initialize, initargs=(str(path),)) as pool:
        batch([task(n, "earlier") for n in NAMES], pool)
        selected, reasons = select_earlier({n: records[(n, "earlier")] for n in NAMES})
        locked = {"selected": selected, "diagnostics": reasons}
        (output/"locked_selection.json").write_text(json.dumps(locked, indent=2), encoding="utf-8")
        print("Locked before later results:", selected, flush=True)
        batch([task(n, phase) for phase in ("earlier_stress", "later", "later_stress") for n in NAMES], pool)
    comparison = {n: {p: records[(n, p)] for p in ("earlier", "earlier_stress", "later", "later_stress")} for n in NAMES}
    candidate, base = comparison[selected], comparison["baseline"]
    later, stressed = candidate["later"], candidate["later_stress"]
    gates = {"earlier_net_improved": candidate["earlier"]["metrics"]["net_pnl"] > base["earlier"]["metrics"]["net_pnl"],
        "earlier_drawdown_reduced": candidate["earlier"]["account"]["m1_close_drawdown"] < base["earlier"]["account"]["m1_close_drawdown"],
        "later_net_positive": later["metrics"]["net_pnl"] > 0,
        "later_target_preserved": later["mean_winner"] >= 100,
        "later_drawdown_reduced": later["account"]["m1_close_drawdown"] < base["later"]["account"]["m1_close_drawdown"],
        "stress_positive_target": stressed["metrics"]["net_pnl"] > 0 and stressed["mean_winner"] >= 100,
        "stress_drawdown_controlled": stressed["account"]["m1_close_drawdown"] <= base["later_stress"]["account"]["m1_close_drawdown"]}
    report = {"plan": plan, "locked_selection": locked, "comparison": comparison,
              "descriptive_checks_for_earlier_nominee": gates, "live_settings_changed": False}
    (output/"report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print("FINISHED", json.dumps({"selected": selected, "gates": gates}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, default=Path("history/mt5_20261111/USDCHF_extended.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/usdchf_loss_reduction"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--register-only", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("workers must be positive")
    run(args.history, args.output, args.workers, args.register_only)


if __name__ == "__main__":
    main()
