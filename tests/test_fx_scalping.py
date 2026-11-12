"""Scalping uses wall-clock deadlines, correct pair valuation and honest gap costs."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import HistoricalData
from src.backtesting.scalping import ScalpPolicy
from src.backtesting.swaps import SwapModel
from src.execution.mt5_adapter import MT5Adapter
from src.risk.sizing import SymbolTradeInfo
from src.services.config import AppConfig, load_config
from src.strategy.liquidity import SweepSignal
from src.tools import backtest_mt5 as replay
from src.tools.capture_fx_history_swaps import exact_symbol
from src.tools import research_fx_scalping as study


def stamp(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())


def test_scalp_schedule_blocks_evening_and_weekend_and_uses_elapsed_time():
    policy = ScalpPolicy(30)
    entry = stamp("2026-01-05T17:45")
    assert not policy.blocks_entry("BUY", entry)
    assert policy.blocks_entry("SELL", stamp("2026-01-05T18:00"))
    assert policy.blocks_entry("BUY", stamp("2026-01-05T04:59"))
    assert policy.blocks_entry("BUY", stamp("2026-01-10T10:00"))
    assert not policy.exit_due("BUY", entry, entry+1799)
    assert policy.exit_due("SELL", entry, entry+1800)
    assert policy.exit_due("BUY", entry, stamp("2026-01-06T10:00"))
    assert policy.deadline(stamp("2026-01-05T18:45")) == stamp("2026-01-05T19:00")


@pytest.mark.parametrize("minutes", [0, -1, 61, True, 1.5])
def test_invalid_scalp_holding_period_rejected(minutes):
    with pytest.raises(ValueError):
        ScalpPolicy(minutes)


def test_no_swap_nomination_rejects_financing_and_no_trade_results():
    def row(net, trades, flat):
        return {"metrics": {"net_pnl": net, "trades": trades},
                "account": {"m1_close_drawdown": 10}, "no_overnight_and_no_swap": flat}
    assert study.nominate({"15": row(0, 0, True), "30": row(-1, 3, True),
                           "60": row(100, 5, False)}) == ("30", ["30"])
    assert study.nominate({"15": row(0, 0, True)}) == (None, [])


def test_history_cache_reloads_when_pair_changes(monkeypatch):
    calls = []
    monkeypatch.setattr(study, "_paths", {"EURUSD": "eur.json", "GBPUSD": "gbp.json"})
    monkeypatch.setattr(study, "_loaded_symbol", None)
    monkeypatch.setattr(study.replay, "_history", None)
    def load(path):
        calls.append(path.name)
        name = "EURUSD" if path.name == "eur.json" else "GBPUSD"
        return {name: NS(symbol=name)}
    monkeypatch.setattr(study, "load_history", load)
    assert study.history_for("EURUSD").symbol == "EURUSD"
    assert study.history_for("EURUSD").symbol == "EURUSD"
    assert study.history_for("GBPUSD").symbol == "GBPUSD"
    assert calls == ["eur.json", "gbp.json"]


def test_financed_gap_position_is_reported_as_failed_no_swap_constraint(monkeypatch):
    monkeypatch.setattr(study, "history_for", lambda symbol: None)
    entry, exit_time = "2026-01-05T17:45:00+00:00", "2026-01-06T08:00:00+00:00"
    trade = dict(side="BUY", volume=.1, entry_time_utc=entry, exit_time_utc=exit_time,
                 swap_events=[(stamp("2026-01-05T21:00"), -.1)])
    monkeypatch.setattr(study.replay, "worker", lambda task: {"trades": [trade]})
    task = [None]*10
    task[7], task[9] = SwapModel(-1, -1), ScalpPolicy(15)
    result = study.worker(("EURUSD", task))
    assert result["late_exits"] == 1
    assert result["utc_overnight_trades"] == 1
    assert result["financing_events"] == result["alternate_clock_financing_events"] == 1
    assert not result["no_overnight_and_no_swap"]
    assert result["trades"] == [trade]


def test_broker_symbol_match_cannot_guess_ambiguous_suffix():
    assert exact_symbol([NS(name="EURUSD-")], "EURUSD").name == "EURUSD-"
    with pytest.raises(ValueError):
        exact_symbol([NS(name="EURUSD-"), NS(name="EURUSD--")], "EURUSD")
    with pytest.raises(ValueError):
        exact_symbol([NS(name="EURGBP-")], "EURUSD")


@pytest.mark.parametrize("side,sign", [("BUY", 1), ("SELL", -1)])
@pytest.mark.parametrize("protection", ["stop", "target"])
def test_scheduled_exit_honors_protection_triggered_at_open(tmp_path, side, sign, protection):
    cfg = load_config(tmp_path/"defaults.json").symbols[0]
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)
    costs = ExecutionCosts("fixed", 0, 0, .2)
    trade = replay.OpenTrade(side, 0, 1.1, 1.1-sign*.002, 1.1+sign*.004,
        .1, 20, "key", "test", 1.1-sign*.002, 1.1+sign*.004, costs=costs)
    price = 1.1+sign*(.005 if protection == "target" else -.003)
    closed = replay._scheduled_exit_at_open(cfg, trade, {"time": 60, "open": price}, info, costs, "scalp_time_exit")
    assert closed.reason == ("take_profit" if protection == "target" else "stop_loss")
    assert closed.exit_price == pytest.approx(trade.tp if protection == "target" else price-sign*.00002)


@pytest.mark.parametrize("side", ["BUY", "SELL"])
@pytest.mark.parametrize("minutes", [15, 30, 60])
def test_offline_scalp_replay_closes_both_sides_without_financing(tmp_path, monkeypatch, side, minutes, gap=False):
    def forbidden(*a, **k):
        raise AssertionError("No broker connection or trade permitted")
    monkeypatch.setattr(MT5Adapter, "initialize", forbidden)
    import MetaTrader5 as mt5
    monkeypatch.setattr(mt5, "order_send", forbidden)
    monkeypatch.setattr(mt5, "order_check", forbidden)
    app = load_config(tmp_path/"defaults.json")
    cfg = replace(app.symbols[0], strategy_mode="trend_micro_burst_v2", confirmation_mode="none",
        allowed_sessions_utc=(), use_bias_filter=False, use_order_block_filter=False,
        risk_pct=.75, max_lot=.5, sl_pips=20, rr=2, cooldown_sec=0)
    app = AppConfig(replace(app.runtime, max_total_open_risk_pct=.75, daily_loss_limit_usd=1000,
        max_profit_per_trade_usd=0, trailing_stop_mode="off"), (cfg,))
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)
    start = datetime(2026, 1, 5, 8, tzinfo=timezone.utc)
    ts = int(start.timestamp())
    bars = [dict(time=ts+i*60, open=1.1, high=1.100001, low=1.099999,
        close=1.1, spread=10, tick_volume=100) for i in range(-120, 240) if not gap or not 15 <= i < 45]
    emitted = []
    def signal(cfg, pip, rates, *args):
        if emitted:
            return None, [], None
        emitted.append(True)
        return SweepSignal(side, 1.0, rates[-2]["time"]), [], None
    monkeypatch.setattr(replay, "_detect_signal_for_cfg", signal)
    result, trades = replay.run_backtest(app, cfg, start, start+timedelta(hours=4),
        initial_equity=10000, costs=ExecutionCosts("fixed", 1, 3.5, .2),
        swaps=SwapModel(-100, -100), history=HistoricalData(cfg.symbol, info, {"M1": bars}),
        end_exclusive=True, overnight_policy=ScalpPolicy(minutes))
    assert len(trades) == 1
    trade = trades[0]
    assert trade.reason == "scalp_time_exit"
    elapsed = (datetime.fromisoformat(trade.exit_time_utc)-datetime.fromisoformat(trade.entry_time_utc)).total_seconds()
    if gap:
        assert elapsed > minutes*60
        assert int(datetime.fromisoformat(trade.exit_time_utc).timestamp()) == ts+45*60
    else:
        assert elapsed == minutes*60
    assert trade.swap_money == 0 and trade.swap_events == []
    assert trade.pnl_money == pytest.approx(-21*trade.volume)
    assert result.ending_equity == pytest.approx(10000+trade.pnl_money)


def test_elapsed_scalp_deadline_cannot_be_delayed_by_counting_missing_bars(tmp_path, monkeypatch):
    test_offline_scalp_replay_closes_both_sides_without_financing(tmp_path, monkeypatch, "BUY", 15, gap=True)
