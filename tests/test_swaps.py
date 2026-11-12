"""Financing regression tests use synthetic history; broker access is prohibited."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import HistoricalData
from src.backtesting.swaps import SwapModel, accrue_swaps, rates_from_snapshot, weekday_weights
from src.execution.mt5_adapter import MT5Adapter
from src.risk.sizing import SymbolTradeInfo
from src.services.config import AppConfig, load_config
from src.tools import backtest_mt5 as replay
from src.tools.research_loss_reduction import account_curve
from src.tools.walk_forward import trade_metrics


def ts(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())


def test_wednesday_triple_friday_single_and_no_weekend_rollover():
    model = SwapModel(-10, 5)
    events = list(model.events(ts("2026-01-07T20:00"), ts("2026-01-12T22:00"), "BUY", .1))
    assert events == [(ts("2026-01-07T21:00"), -3), (ts("2026-01-08T21:00"), -1),
                      (ts("2026-01-09T21:00"), -1), (ts("2026-01-12T21:00"), -1)]


@pytest.mark.parametrize("day", [-1, 7, True, 1.5])
def test_invalid_broker_triple_day_cannot_silently_wrap_to_weekend(day):
    with pytest.raises(ValueError, match="weekday"):
        weekday_weights({"swap_rollover3days": day})
    assert weekday_weights({"swap_rollover3days": day}, 3) == (1, 1, 3, 1, 1, 0, 0)


def test_broker_weekday_mapping_preserves_friday_triple():
    assert weekday_weights({"swap_rollover3days": 5}) == (1, 1, 1, 1, 3, 0, 0)


def test_stress_doubles_debits_but_never_inflates_credits():
    model = SwapModel(-10, 5, debit_multiplier=2)
    a, b = ts("2026-01-05T20:00"), ts("2026-01-05T22:00")
    assert list(model.events(a, b, "BUY", .1))[0][1] == -2
    assert list(model.events(a, b, "SELL", .1))[0][1] == .5


def test_rollover_timezone_entry_boundary_and_idempotent_accrual():
    event = ts("2026-01-05T21:00")
    trade = SimpleNamespace(entry_time=event-60, side="BUY", volume=.1,
                            swap_last_timestamp=None, swap_events=[], swap_money=0)
    model = SwapModel(-10, 5)
    assert accrue_swaps(trade, event-1, model) == []
    assert accrue_swaps(trade, event, model) == [(event, -1)]
    assert accrue_swaps(trade, event+60, model) == []
    assert trade.swap_money == -1
    assert list(model.events(event, event+60, "BUY", .1)) == []
    assert list(replace(model, timezone="Etc/GMT-2").events(event-60, event, "BUY", .1)) == []


@pytest.mark.parametrize("mode", [2, 3, 5, 6, 7, 8])
def test_unsupported_swap_modes_fail_closed(mode):
    with pytest.raises(ValueError, match="Unsupported"):
        rates_from_snapshot({"swap_mode": mode}, None, "EUR")


def test_point_and_deposit_rates_convert_without_pip_factor_error():
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1.1, .00001)
    snapshot = dict(swap_mode=1, point=.00001, swap_long=-4, swap_short=2)
    assert rates_from_snapshot(snapshot, info, "EUR") == pytest.approx((-4.4, 2.2))
    assert rates_from_snapshot(snapshot | {"swap_mode": 4}, info, "EUR") == (-4, 2)
    assert rates_from_snapshot({"swap_mode": 0}, info, "EUR") == (0, 0)


@pytest.mark.parametrize("capital", [2000, 10000])
def test_research_worker_uses_requested_capital_for_replay_and_reports(monkeypatch, capital):
    from src.tools import research_swap_2k as study
    def run(*args, **kwargs):
        assert kwargs["initial_equity"] == capital
        return SimpleNamespace(ending_equity=capital), []
    def curve(trades, history, costs, initial_equity):
        assert initial_equity == capital
        return {"start_equity": capital, "end_equity": capital}
    monkeypatch.setattr(study, "run_backtest", run)
    monkeypatch.setattr(study, "account_curve", curve)
    monkeypatch.setattr(study, "history_coverage", lambda *a, **k: None)
    now = datetime(2026, 1, 5, tzinfo=timezone.utc)
    result = study.worker(("normal", "full", None, None, now, now, None, None, capital))
    assert result["account"]["start_equity"] == capital
    assert result["metrics"]["return_pct"] == 0


@pytest.mark.parametrize("capital", [0, -100, float("inf"), float("nan")])
def test_invalid_research_capital_rejected_before_data_or_broker_access(capital):
    from src.tools.research_swap_2k import run
    with pytest.raises(ValueError, match="capital"):
        run(None, None, None, capital=capital)


@pytest.mark.parametrize("daily_limit,expected_reason", [(40, "daily_loss_guard_close"), (1000, "end_of_test")])
@pytest.mark.parametrize("capital,volume", [(2000, .07), (10000, .37)])
def test_replay_books_swap_once_and_daily_guard_sees_it(tmp_path, monkeypatch, daily_limit, expected_reason, capital, volume):
    def forbidden(*args, **kwargs):
        raise AssertionError("No broker or trading allowed")
    monkeypatch.setattr(MT5Adapter, "initialize", forbidden)
    import MetaTrader5 as mt5
    monkeypatch.setattr(mt5, "order_send", forbidden)
    monkeypatch.setattr(mt5, "order_check", forbidden)
    app = load_config(tmp_path/"defaults.json")
    cfg = replace(app.symbols[0], risk_pct=.75, max_lot=.5, strategy_mode="trend_micro_burst_v2",
        confirmation_mode="none", allowed_sessions_utc=(), use_bias_filter=False,
        use_order_block_filter=False, cooldown_sec=0, sl_pips=20, rr=2)
    app = AppConfig(replace(app.runtime, max_total_open_risk_pct=.75,
        daily_loss_limit_usd=daily_limit, close_positions_on_daily_loss=True,
        max_profit_per_trade_usd=0, trailing_stop_mode="off"), (cfg,))
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)
    start = datetime(2026, 1, 5, 20, tzinfo=timezone.utc)
    stamp = int(start.timestamp())
    bars = [dict(time=stamp+i*60, open=1.1, high=1.100001, low=1.099999,
                 close=1.1, spread=0, tick_volume=100) for i in range(180)]
    history = HistoricalData(cfg.symbol, info, {"M1": bars})
    from src.strategy.liquidity import SweepSignal
    monkeypatch.setattr(replay, "_detect_signal_for_cfg", lambda cfg, pip, rates, *args:
        (SweepSignal("BUY", 1.0, rates[-2]["time"]), [], None))
    costs = ExecutionCosts("fixed", 0, 3.5, 0)
    result, trades = replay.run_backtest(app, cfg, start, start+timedelta(hours=3),
        initial_equity=capital, costs=costs, swaps=SwapModel(-1000, 0), history=history, end_exclusive=True)
    assert len(trades) == 1
    trade = trades[0]
    assert trade.reason == expected_reason
    loss = volume * (1000 + 7)
    assert trade.volume == pytest.approx(volume)
    assert trade.swap_money == pytest.approx(-1000*volume)
    assert trade.pnl_money == pytest.approx(-loss)
    assert result.ending_equity == pytest.approx(capital-loss)
    assert trade.gross_pnl_money == pytest.approx(0)
    assert len(trade.swap_events) == 1
    metrics = trade_metrics(trades, capital)
    assert metrics["net_pnl"] == pytest.approx(-loss)
    assert metrics["return_pct"] == pytest.approx(-loss/capital*100)
    assert metrics["max_realized_drawdown"] == pytest.approx(loss)
    curve = account_curve(trades, history, costs, initial_equity=capital)
    assert curve["end_equity"] == pytest.approx(result.ending_equity)
    assert curve["m1_close_drawdown"] == pytest.approx(loss)
