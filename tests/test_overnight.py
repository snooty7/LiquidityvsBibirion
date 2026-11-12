"""Offline no-overnight policy checks; every broker connection/order is forbidden."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import HistoricalData
from src.backtesting.overnight import OvernightPolicy
from src.backtesting.swaps import SwapModel
from src.execution.mt5_adapter import MT5Adapter
from src.risk.sizing import SymbolTradeInfo
from src.services.config import AppConfig, load_config
from src.strategy.liquidity import SweepSignal
from src.tools import backtest_mt5 as replay


def stamp(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())


def test_cutoff_entry_block_midnight_reset_and_side_scope():
    policy = OvernightPolicy(("SELL",))
    cutoff = stamp("2026-01-05T20:55")
    assert not policy.blocks_entry("SELL", cutoff-1)
    assert policy.blocks_entry("SELL", cutoff)
    assert policy.blocks_entry("SELL", cutoff+299)
    assert not policy.blocks_entry("SELL", cutoff+300)
    assert not policy.blocks_entry("BUY", cutoff)
    assert not policy.exit_due("SELL", cutoff-100, cutoff-1)
    assert policy.exit_due("SELL", cutoff-100, cutoff)
    # No invented Friday fill when trading resumes after a weekend gap.
    assert policy.exit_due("SELL", stamp("2026-01-09T10:00"), stamp("2026-01-12T00:00"))
    assert not policy.exit_due("BUY", cutoff-100, cutoff)
    assert OvernightPolicy(timezone="Etc/GMT-2").deadline(cutoff-100) == cutoff+3600


@pytest.mark.parametrize("minutes", [0, 1440, 1.5, True])
def test_invalid_cutoff_rejected(minutes):
    with pytest.raises(ValueError, match="Cutoff"):
        OvernightPolicy(minutes_before=minutes)


@pytest.mark.parametrize("side,sides,flatten", [("SELL", ("SELL",), True),
    ("BUY", ("SELL",), False), ("BUY", ("BUY", "SELL"), True)])
@pytest.mark.parametrize("gap", [False, True])
def test_replay_uses_actual_quotes_and_keeps_swap_after_missing_cutoff(tmp_path, monkeypatch, side, sides, flatten, gap,
                                                                    daily_limit=1000, cutoff_spike=False):
    def forbidden(*a, **k):
        raise AssertionError("Broker use forbidden")
    monkeypatch.setattr(MT5Adapter, "initialize", forbidden)
    import MetaTrader5 as mt5
    monkeypatch.setattr(mt5, "order_send", forbidden)
    monkeypatch.setattr(mt5, "order_check", forbidden)
    base = load_config(tmp_path/"defaults.json")
    cfg = replace(base.symbols[0], risk_pct=.75, max_lot=.5, strategy_mode="trend_micro_burst_v2",
        confirmation_mode="none", allowed_sessions_utc=(), use_bias_filter=False,
        use_order_block_filter=False, cooldown_sec=0, sl_pips=20, rr=2)
    app = AppConfig(replace(base.runtime, max_total_open_risk_pct=.75, daily_loss_limit_usd=daily_limit,
        max_profit_per_trade_usd=0, trailing_stop_mode="off"), (cfg,))
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)
    start = datetime(2026, 1, 5, 20, tzinfo=timezone.utc)
    ts = int(start.timestamp())
    bars = [dict(time=ts+i*60, open=1.1, high=1.100001, low=1.099999,
        close=1.1, spread=10, tick_volume=100) for i in range(180) if not gap or not 55 <= i < 65]
    if cutoff_spike:
        next(b for b in bars if b["time"] == ts+55*60).update(high=1.2, close=1.2)
    history = HistoricalData(cfg.symbol, info, {"M1": bars})
    monkeypatch.setattr(replay, "_detect_signal_for_cfg", lambda cfg, pip, rates, *args:
        (SweepSignal(side, 1.0, rates[-2]["time"]) if rates[-2]["time"] < ts+1800 else None, [], None))
    costs = ExecutionCosts("fixed", 1, 3.5, .2)
    policy = OvernightPolicy(sides)
    result, trades = replay.run_backtest(app, cfg, start, start+timedelta(hours=3),
        initial_equity=10000, costs=costs, swaps=SwapModel(-100, -100), history=history,
        end_exclusive=True, overnight_policy=policy)
    assert len(trades) == 1
    trade = trades[0]
    reason = "daily_loss_guard_close" if daily_limit == 10 else ("pre_rollover_exit" if flatten else "end_of_test")
    assert trade.reason == reason
    if flatten:
        assert int(datetime.fromisoformat(trade.exit_time_utc).timestamp()) == ts+(65 if gap else 55)*60
    assert trade.swap_money == pytest.approx(-100*trade.volume if gap or not flatten else 0)
    assert trade.commission_cost_money == pytest.approx(7*trade.volume)
    assert trade.spread_cost_money == pytest.approx(10*trade.volume)
    assert trade.slippage_cost_money == pytest.approx(4*trade.volume)
    assert trade.pnl_money == pytest.approx(trade.swap_money-21*trade.volume)
    assert result.ending_equity == pytest.approx(10000+trade.pnl_money)
    assert replay._build_entry_trade(cfg, app.runtime, info, 10000, sides[0], ts+55*60, 1.1,
                                    "key", "test", overnight_policy=policy) is None


def test_daily_loss_protection_takes_priority_over_overdue_cutoff(tmp_path, monkeypatch):
    test_replay_uses_actual_quotes_and_keeps_swap_after_missing_cutoff(
        tmp_path, monkeypatch, "SELL", ("SELL",), True, True, daily_limit=10)


def test_cutoff_fill_cannot_use_later_high_or_close_of_its_minute(tmp_path, monkeypatch):
    test_replay_uses_actual_quotes_and_keeps_swap_after_missing_cutoff(
        tmp_path, monkeypatch, "BUY", ("BUY", "SELL"), True, False, cutoff_spike=True)


def test_baseline_audit_normalizes_swap_event_tuples_but_rejects_changed_values():
    from src.tools.research_no_overnight import audit_baseline
    previous = {"results": {"swap": {"full": {"scenario": "swap", "trades": [{"swap_events": [[100, -2]]}]}}}}
    actual = {"baseline_swap": {"full": {"scenario": "baseline_swap", "trades": [{"swap_events": [(100, -2)]}]}}}
    audit_baseline(actual, previous, ["swap"])
    actual["baseline_swap"]["full"]["trades"][0]["swap_events"] = [(100, -3)]
    with pytest.raises(ValueError, match="Baseline changed"):
        audit_baseline(actual, previous, ["swap"])
