"""Regression coverage for isolated carry hypotheses and earlier-only selection."""
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.backtesting.costs import ExecutionCosts
from src.backtesting.financing_exits import FinancingExitPolicy, LateSellEntryPolicy
from src.backtesting.history import HistoricalData
from src.backtesting.swaps import SwapModel
from src.engine.orchestrator import compute_r_multiple_trailing_stop
from src.risk.sizing import SymbolTradeInfo
from src.services.config import AppConfig, load_config
from src.strategy.liquidity import SweepSignal
from src.tools import backtest_mt5 as replay
from src.tools.research_financing_resilience import VARIANTS, nominate, task
from src.tools.research_usdchf_risk05 import settings


def ts(value):
    return int(datetime.fromisoformat(value+"+00:00").timestamp())


def test_triple_deadline_uses_day_ending_at_midnight_and_blocks_only_due_sell():
    policy = FinancingExitPolicy(("SELL",), "Etc/GMT-3")
    entry = ts("2026-01-05T08:00")  # Monday, next triple is Wednesday night.
    cutoff = ts("2026-01-07T20:55")
    assert policy.deadline(entry) == cutoff
    assert not policy.exit_due("SELL", entry, cutoff-1)
    assert policy.exit_due("SELL", entry, cutoff)
    assert not policy.exit_due("BUY", entry, cutoff+86400)
    assert not policy.blocks_entry("SELL", cutoff-1)
    assert policy.blocks_entry("SELL", cutoff)
    assert not policy.blocks_entry("BUY", cutoff)
    assert not policy.blocks_entry("SELL", ts("2026-01-07T21:00"))


@pytest.mark.parametrize("entry,expected", [
    ("2026-01-05T08:00", "2026-01-06T20:55"),  # first ordinary night allowed
    ("2026-01-07T08:00", "2026-01-07T20:55"),  # triple exceeds budget immediately
    ("2026-01-09T08:00", "2026-01-12T20:55"),  # Friday unit, weekend zero, Monday second
])
def test_one_unit_carry_deadline_counts_units_not_calendar_nights(entry, expected):
    policy = FinancingExitPolicy(("SELL",), "Etc/GMT-3", mode="one_unit")
    assert policy.deadline(ts(entry)) == ts(expected)
    assert policy.exit_due("SELL", ts(entry), ts(expected)+4*86400)
    assert not policy.blocks_entry("SELL", ts("2026-01-05T20:59"))


def test_entry_only_blackout_has_exact_boundary_and_never_forces_exit():
    policy = LateSellEntryPolicy(("SELL",), "Etc/GMT-3")
    start = ts("2026-01-05T19:30")
    assert not policy.blocks_entry("SELL", start-1)
    assert policy.blocks_entry("SELL", start)
    assert not policy.blocks_entry("BUY", start)
    assert not policy.blocks_entry("SELL", start+90*60)
    assert not policy.exit_due("SELL", start-3600, start+3*86400)


@pytest.mark.parametrize("kwargs", [dict(mode="unknown"), dict(charge_weights=(1,)*6),
    dict(charge_weights=(0,)*7), dict(charge_weights=(1,)*7),
    dict(charge_weights=(float("nan"), 1, 3, 1, 1, 0, 0))])
def test_invalid_financing_schedule_rejected(kwargs):
    with pytest.raises(ValueError):
        FinancingExitPolicy(**kwargs)


def test_hypotheses_keep_funding_sizing_daily_guard_and_signal_definition(tmp_path):
    config = load_config(tmp_path/"defaults.json")
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)
    source = SimpleNamespace(config=config, symbol=replace(config.symbols[0], symbol="USDCHF"))
    app, cfg, _ = settings(source, info)
    swap = SwapModel(1, -20)
    for name in VARIANTS:
        job = task(name, 2, "full", True, app, cfg, swap)
        assert job[8] == 10000 and job[3].risk_pct == .5
        assert job[2].runtime == app.runtime
        changed = {k for k, v in asdict(cfg).items() if v != getattr(job[3], k)}
        assert changed == ({"trailing_gap_r"} if name == "trail_gap_0_75" else set())
        assert job[3].max_lot == .5 and job[3].trailing_activation_r == 1.5
        assert job[6] == ExecutionCosts("historical", 2, 7, .4)
        assert job[7].debit_multiplier == 2 and job[7].buy_per_lot == 1
        assert job[7].timezone == "Etc/GMT-2"


@pytest.mark.parametrize("side,sign", [("BUY", 1), ("SELL", -1)])
def test_tighter_trailing_uses_shared_live_helper_and_never_widens_stop(side, sign):
    stop = 1.1-sign*.002
    for move in (.5, 1.49, 1.5, 2, .6, 3, .1):
        result = compute_r_multiple_trailing_stop(side=side, open_price=1.1,
            current_exit_price_value=1.1+sign*move*.002, current_sl=stop,
            risk_distance_price=.002, activation_r=1.5, gap_r=.75)
        if move < 1.5:
            assert result is None
        if result is not None:
            assert sign*(result-stop) >= 0
            stop = result


def test_nomination_cannot_read_later_results_or_hide_earlier_losses():
    rows = {v+"_gmt3_stress": {"earlier": {"metrics": {"net_pnl": -100},
        "account": {"m1_close_drawdown": 50}}, "later": {"metrics": {"net_pnl": 999999}}} for v in VARIANTS}
    rows["one_unit_carry_gmt3_stress"]["earlier"]["account"]["m1_close_drawdown"] = 20
    assert nominate(rows)[0] == "one_unit_carry"
    rows["original_gmt3_stress"]["later"] = None
    assert nominate(rows)[0] == "one_unit_carry"


@pytest.mark.parametrize("gap", [False, True])
def test_financing_exit_uses_actual_quote_and_keeps_swap_after_missing_cutoff(tmp_path, monkeypatch, gap):
    def forbidden(*args, **kwargs):
        raise AssertionError("Terminal connection or orders forbidden")
    import MetaTrader5 as mt5
    monkeypatch.setattr(mt5, "initialize", forbidden)
    monkeypatch.setattr(mt5, "order_send", forbidden)
    monkeypatch.setattr(mt5, "order_check", forbidden)
    base = load_config(tmp_path/"defaults.json")
    cfg = replace(base.symbols[0], timeframe="M1", strategy_mode="trend_micro_burst_v2",
        confirmation_mode="none", allowed_sessions_utc=(), use_bias_filter=False,
        use_order_block_filter=False, risk_pct=.5, max_lot=.5, sl_pips=20, rr=2, cooldown_sec=0)
    app = AppConfig(replace(base.runtime, max_total_open_risk_pct=.5, daily_loss_limit_usd=1000,
        max_profit_per_trade_usd=0, trailing_stop_mode="off"), (cfg,))
    start = datetime(2026, 1, 7, 20, tzinfo=timezone.utc)  # Wednesday triple night
    stamp = int(start.timestamp())
    bars = [dict(time=stamp+i*60, open=1.1, high=1.100001, low=1.099999,
        close=1.1, spread=10, tick_volume=100) for i in range(-120, 121)
        if not gap or not 55 <= i < 70]
    emitted = []
    def signal(cfg, pip, rates, *args):
        if emitted:
            return None, [], None
        emitted.append(True)
        return SweepSignal("SELL", 1., rates[-2]["time"]), [], None
    monkeypatch.setattr(replay, "_detect_signal_for_cfg", signal)
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)
    result, trades = replay.run_backtest(app, cfg, start, start+timedelta(hours=2),
        initial_equity=10000, costs=ExecutionCosts("fixed", 1, 7, .4),
        swaps=SwapModel(1, -20, debit_multiplier=2), history=HistoricalData(cfg.symbol, info, {"M1": bars}),
        end_exclusive=True, overnight_policy=FinancingExitPolicy(("SELL",)))
    assert len(trades) == 1 and trades[0].reason == "triple_swap_exit"
    trade = trades[0]
    assert int(datetime.fromisoformat(trade.exit_time_utc).timestamp()) == stamp+(70 if gap else 55)*60
    assert trade.swap_money == pytest.approx(-120*trade.volume if gap else 0)
    assert len(trade.swap_events) == int(gap)
    assert result.ending_equity == pytest.approx(10000+trade.pnl_money)
