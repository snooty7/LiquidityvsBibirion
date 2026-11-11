"""Risk regression tests use temporary SQLite databases and fake broker adapters only."""
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pytest

from src.engine import orchestrator as o
from src.execution import mt5_adapter as m
from src.persistence.repository import SQLiteRepository
from src.persistence.recovery import build_pending_setup_record
from src.risk.sizing import (
    RiskSizingError, SymbolTradeInfo, calc_lot_by_risk, calc_position_risk_money,
    daily_loss_limit_hit,
)
from src.services.config import AppConfig, load_config
from src.strategy.confirmations import ConfirmationResult
from src.tools import backtest_mt5 as b


@pytest.fixture
def info():
    return SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)


@pytest.fixture
def app(tmp_path):
    base = load_config(tmp_path / "defaults.json")
    cfg = replace(base.symbols[0], risk_pct=.1, min_lot=0, max_lot=1,
                  sl_pips=10, rr=2, strategy_mode="liquidity_sweep",
                  allowed_sessions_utc=(), use_bias_filter=False, use_order_block_filter=False)
    runtime = replace(base.runtime, dry_run=False, daily_loss_limit_usd=50,
                      close_positions_on_daily_loss=True, risk_close_retry_sec=20,
                      max_total_open_risk_pct=.5, max_profit_per_trade_usd=0,
                      trailing_stop_mode="off", push_notifications_enabled=False,
                      db_path=str(tmp_path / "state.db"), log_file=str(tmp_path / "events.csv"))
    return AppConfig(runtime, (cfg,))


@pytest.fixture
def repo(app):
    value = SQLiteRepository(app.runtime.db_path)
    yield value
    value.close()


def position(**changes):
    data = dict(ticket=1, type=0, magic=92001, volume=.1, price_open=1.1,
                sl=1.099, tp=1.11, profit=0, time=100, comment="test")
    return NS(**(data | changes))


@pytest.mark.parametrize("risk,minimum", [(.1, 0), (.5, .2)])
def test_unaffordable_minimum_never_increases_risk(info, risk, minimum):
    with pytest.raises(RiskSizingError, match="Minimum"):
        calc_lot_by_risk(100, 10, risk, info, 1, min_lot=minimum)


def test_volume_rounds_down_and_never_breaks_budget(info):
    volume = calc_lot_by_risk(1000, 10, .16, info, 1)
    assert volume == .01
    assert calc_position_risk_money(1.1, 1.099, volume, info) <= 1.6
    assert calc_lot_by_risk(10000, 10, 1, info, .105) == .1
    with pytest.raises(RiskSizingError):
        calc_lot_by_risk(10000, 10, 1, info, .01, min_lot=.015)


@pytest.mark.parametrize("field,value", [("trade_tick_value", 0), ("trade_tick_size", 0),
                                        ("trade_tick_value", float("nan")), ("point", 0)])
def test_unknown_valuation_rejects_sizing_and_counts_as_unknown_exposure(info, field, value):
    bad = replace(info, **{field: value})
    with pytest.raises(RiskSizingError):
        calc_lot_by_risk(10000, 10, 1, bad, 1)
    assert calc_position_risk_money(1.1, 1.099, .1, bad) == float("inf")


@pytest.mark.parametrize("risk", [0, -1, float("nan"), float("inf")])
def test_invalid_risk_cannot_produce_a_minimum_lot(info, risk):
    with pytest.raises(RiskSizingError):
        calc_lot_by_risk(10000, 10, risk, info, 1)


class DailyAdapter:
    def __init__(self, pnl=-60):
        self.pnl = pnl
        self.positions = [position()]
        self.attempts = 0
        self.close_ok = False

    def realized_pnl_today(self, *args):
        if isinstance(self.pnl, Exception):
            raise self.pnl
        return self.pnl

    def positions_get(self, *args, **kwargs):
        return self.positions

    def close_position_market_with_fallback(self, **kwargs):
        self.attempts += 1
        if self.close_ok:
            self.positions = []
        return m.CloseResult(self.close_ok, 10009 if self.close_ok else 10021, None, None, 1.1, "fake")


def guard(adapter, app, state, repo):
    from pathlib import Path
    return o.apply_daily_loss_guard(adapter, app, state, Path(app.runtime.log_file), repo)


def test_daily_liquidation_retries_after_restart_and_respects_backoff(app, repo, monkeypatch):
    adapter = DailyAdapter()
    repo.upsert_open_position(o.position_to_record(app.symbols[0], adapter.positions[0], None))
    state = o.GlobalState()
    clock = [1000]
    monkeypatch.setattr(o.time, "time", lambda: clock[0])
    assert guard(adapter, app, state, repo)
    assert adapter.attempts == 1
    assert repo.list_risk_retries()[0].reason == "daily_loss"
    assert repo.get_open_position(1).status == "OPEN"
    assert guard(adapter, app, state, repo)
    assert adapter.attempts == 1
    # Reopen SQLite and restore the latched state, as startup recovery does.
    restored_repo = SQLiteRepository(app.runtime.db_path)
    try:
        saved = restored_repo.get_guard_state()
        restored = o.GlobalState(saved.day_key, saved.daily_realized_pnl,
                                 saved.daily_loss_reached, saved.daily_loss_announced)
        clock[0] = 1021
        adapter.close_ok = True
        assert guard(adapter, app, restored, restored_repo)
        assert adapter.attempts == 2
        assert restored_repo.list_risk_retries() == []
        assert restored_repo.get_open_position(1).status == "CLOSED"
        assert guard(adapter, app, restored, restored_repo)
        assert adapter.attempts == 2
    finally:
        restored_repo.close()


def test_history_failure_blocks_entries_without_latching_and_recovers(app, repo, monkeypatch):
    fake = NS(history_deals_get=lambda *args: None)
    monkeypatch.setattr(m, "mt5", fake)
    with pytest.raises(m.HistoryUnavailableError):
        m.MT5Adapter().realized_pnl_today({92001}, datetime.now(timezone.utc))
    adapter = DailyAdapter(m.HistoryUnavailableError("offline"))
    state = o.GlobalState()
    assert guard(adapter, app, state, repo)
    assert not state.daily_loss_reached
    assert adapter.attempts == 0
    adapter.pnl = -10
    assert not guard(adapter, app, state, repo)
    assert state.daily_realized_pnl == -10


def test_daily_pnl_includes_entry_exit_and_reversal_costs(app, repo, monkeypatch):
    deals = [NS(magic=92001, entry=0, profit=0, commission=-3, swap=0, fee=-1),
             NS(magic=92001, entry=1, profit=-48, commission=-2, swap=-1, fee=0),
             NS(magic=92001, entry=2, profit=4, commission=-1, swap=0, fee=0),
             NS(magic=99999, entry=1, profit=999, commission=0, swap=0, fee=0)]
    monkeypatch.setattr(m, "mt5", NS(history_deals_get=lambda *args: deals))
    value = m.MT5Adapter().realized_pnl_today({92001}, datetime.now(timezone.utc))
    assert value == -52
    adapter = DailyAdapter(value)
    assert guard(adapter, app, o.GlobalState(), repo)


def test_disabled_daily_loss_limit_matches_backtest(app, repo):
    for limit in (0, -50):
        disabled = AppConfig(replace(app.runtime, daily_loss_limit_usd=limit), app.symbols)
        assert not guard(DailyAdapter(-100), disabled, o.GlobalState(), repo)
        assert not daily_loss_limit_hit(-100, limit)


class MarketAdapter:
    pip_size = staticmethod(m.MT5Adapter.pip_size)

    def __init__(self, info, positions=(), equity=10000):
        self.info = NS(**info.__dict__, trade_stops_level=0)
        self.positions = list(positions)
        self.equity = equity
        self.price = 1.1
        self.modifications = []

    def symbol_info(self, *args): return self.info
    def positions_get(self, *args, **kwargs): return self.positions
    def symbol_tick(self, *args): return NS(bid=self.price, ask=self.price)
    def account_equity(self): return self.equity
    def spread_pips(self, *args): return .5
    def copy_rates(self, *args):
        return [dict(time=t, open=1.1, high=1.1005, low=1.0995, close=1.1) for t in (100, 400, 700)]
    def modify_position_protection(self, symbol, pos, *, sl, tp):
        self.modifications.append(sl)
        pos.sl, pos.tp = sl, tp
        return m.ModifyResult(True, 10009, sl, tp, None)
    def send_market_order_with_price_protection(self, **kwargs):
        raise AssertionError("No trade should be sent")


def confirmed_setup(repo, cfg, risk_context):
    record = build_pending_setup_record(
        symbol=cfg.symbol, timeframe=cfg.timeframe, side="BUY", level=1.1,
        candle_time=100, signal_key="BUY|1.10000", expires_at=10000,
        context={"risk": risk_context}, initial_status="PENDING",
    )
    record, _ = repo.create_or_get_pending_setup(record)
    return o.pending_from_record(record)


@pytest.mark.parametrize("context,equity,minimum,event", [
    ({"risk_pct_override": 1.0}, 10000, 0, "SKIP_PORTFOLIO_CAP"),
    ({}, 100, .2, "SKIP_INVALID_RISK"),
])
def test_live_and_backtest_reject_over_cap_or_unaffordable_orders(
    app, repo, info, monkeypatch, context, equity, minimum, event,
):
    from pathlib import Path
    cfg = replace(app.symbols[0], min_lot=minimum)
    app = AppConfig(app.runtime, (cfg,))
    pending = confirmed_setup(repo, cfg, context)
    monkeypatch.setattr(o, "evaluate_pending_confirmation",
                        lambda *args: ConfirmationResult(True, False, "confirmed"))
    monkeypatch.setattr(o, "detect_sweep_signal", lambda *args: None)
    adapter = MarketAdapter(info, equity=equity)
    o.process_symbol(adapter, cfg, app, o.SymbolState(pending_setup=pending),
                     Path(app.runtime.log_file), repo)
    assert event in Path(app.runtime.log_file).read_text()
    assert b._build_entry_trade(cfg, app.runtime, info, equity, "BUY", 1000, 1.1,
                                "key", "confirmed", pending) is None


def test_portfolio_cap_uses_measured_proposed_and_unknown_open_risk(app, info):
    adapter = MarketAdapter(info)
    cfg = app.symbols[0]
    assert o.portfolio_caps_message(adapter, app, cfg, 10000, 60) is not None
    assert o.portfolio_caps_message(adapter, app, cfg, 10000, 50) is None
    adapter.positions = [position(sl=0)]
    assert o.portfolio_caps_message(adapter, app, cfg, 10000, 1) is not None


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_live_trailing_matches_backtest_and_survives_database_reopen(app, repo, info, side):
    from pathlib import Path
    cfg = app.symbols[0]
    runtime = replace(app.runtime, trailing_stop_mode="r_multiple",
                      trailing_activation_r=1, trailing_gap_r=1, trailing_remove_tp_on_activation=True)
    app = AppConfig(runtime, (cfg,))
    sign = 1 if side == "BUY" else -1
    pos = position(type=0 if sign == 1 else 1, sl=1.1-sign*.001, tp=1.1+sign*.01)
    adapter = MarketAdapter(info, [pos])
    repo.ensure_position_risk_distance(1, .001)
    trade = b.OpenTrade(side, 100, 1.1, pos.sl, pos.tp, .1, 10, "key", "ok", pos.sl, pos.tp)
    for move in (.0015, .002, .003):
        adapter.price = 1.1 + sign*move
        reopened = SQLiteRepository(app.runtime.db_path)
        try:
            o.manage_symbol_positions(adapter, cfg, app, o.SymbolState(), Path(runtime.log_file), reopened)
            assert reopened.get_position_risk_distance(1) == .001
        finally:
            reopened.close()
        # Keep the test bar inside the existing protection, then advance its close.
        bar = dict(time=1000, open=adapter.price, close=adapter.price,
                   low=adapter.price-.00001, high=adapter.price+.00001)
        trade, closed = b._apply_open_trade_bar(cfg, runtime, trade, bar, info)
        assert closed is None
        assert pos.sl == pytest.approx(trade.sl)
        assert pos.tp == trade.tp == 0
        limit, _, _ = o.resolve_loss_guard(runtime, pos, info, .001)
        assert limit == pytest.approx(10)


class PartialBroker:
    ORDER_TYPE_BUY = POSITION_TYPE_BUY = ORDER_TIME_GTC = ORDER_FILLING_FOK = 0
    ORDER_TYPE_SELL = TRADE_ACTION_DEAL = ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_DONE_PARTIAL = 10010

    def __init__(self, finish):
        self.remaining = .1
        self.finish = finish
        self.requests = []

    def order_send(self, request):
        self.requests.append(request)
        filled = self.remaining if self.finish and len(self.requests) > 1 else self.remaining / 2
        self.remaining -= filled
        return NS(retcode=10009 if self.remaining == 0 else 10010, order=1, deal=2, volume=filled)


@pytest.mark.parametrize("finish", [True, False])
def test_partial_close_reconciles_and_only_reports_success_when_flat(monkeypatch, finish):
    fake = PartialBroker(finish)
    monkeypatch.setattr(m, "mt5", fake)
    adapter = m.MT5Adapter()
    monkeypatch.setattr(adapter, "ensure_symbol", lambda *args: None)
    monkeypatch.setattr(adapter, "symbol_tick", lambda *args: NS(bid=1.1, ask=1.1002))
    monkeypatch.setattr(adapter, "positions_get", lambda *args, **kwargs:
                        [position(volume=fake.remaining)] if fake.remaining else [])
    result = adapter.close_position_market_with_fallback("EURUSD", position(), 92001, "daily_loss")
    assert result.ok is finish
    assert fake.requests[0]["volume"] == .1
    assert fake.requests[1]["volume"] == .05
    assert len(fake.requests) <= 9
    assert (fake.remaining == 0) is finish


@pytest.mark.parametrize("unavailable", [False, True])
def test_partial_close_never_resends_original_volume_when_reconciliation_fails(monkeypatch, unavailable):
    fake = PartialBroker(False)
    monkeypatch.setattr(m, "mt5", fake)
    adapter = m.MT5Adapter()
    monkeypatch.setattr(adapter, "ensure_symbol", lambda *args: None)
    monkeypatch.setattr(adapter, "symbol_tick", lambda *args: NS(bid=1.1, ask=1.1002))
    def snapshot(*args, **kwargs):
        if unavailable:
            raise RuntimeError("offline")
        return [position(volume=.1)]  # stale snapshot
    monkeypatch.setattr(adapter, "positions_get", snapshot)
    result = adapter.close_position_market_with_fallback("EURUSD", position(), 92001, "daily_loss")
    assert not result.ok
    assert len(fake.requests) == 1


def test_backtest_entry_and_exit_commissions_match_broker_accounting(app, info, monkeypatch):
    cfg = replace(app.symbols[0], risk_pct=1, max_lot=.1, strategy_mode="trend_micro_burst_v2",
                  confirmation_mode="none", cooldown_sec=0, sl_pips=100, rr=10)
    runtime = replace(app.runtime, daily_loss_limit_usd=2, max_total_open_risk_pct=0)
    app = AppConfig(runtime, (cfg,))
    start = datetime(2026, 1, 5, 8, tzinfo=timezone.utc)
    timestamp = int(start.timestamp())
    def bars(step, count):
        return [dict(time=timestamp+i*step, open=1.1, high=1.10001, low=1.09999,
                     close=1.1, spread=0) for i in range(count)]
    m1, m5 = bars(60, 100), bars(300, 20)
    class HistoryOnlyAdapter:
        def __init__(self, **kwargs): pass
        def initialize(self): pass
        def shutdown(self): pass
        def ensure_symbol(self, symbol): pass
        def symbol_info(self, symbol): return NS(**info.__dict__)
    monkeypatch.setattr(b, "MT5Adapter", HistoryOnlyAdapter)
    HistoryOnlyAdapter.pip_size = staticmethod(m.MT5Adapter.pip_size)
    monkeypatch.setattr(b, "_fetch_chunked_rates",
                        lambda adapter, symbol, tf, *args: m1 if tf == "M1" else m5)
    from src.strategy.liquidity import SweepSignal
    monkeypatch.setattr(b, "_detect_signal_for_cfg",
                        lambda cfg, pip, rates, *args: (SweepSignal("BUY", 1.0+rates[-2]["time"]*1e-9,
                                                                 rates[-2]["time"]), [], None))
    result, trades = b.run_backtest(app, cfg, start, start, initial_equity=10000, commission_per_lot=30)
    # Entry commission alone breaches the daily limit. Liquidation occurs on the
    # next simulated polling bar; both sides are charged once, then entries stop.
    assert len(trades) == 1
    assert trades[0].reason == "daily_loss_guard_close"
    assert trades[0].pnl_money == pytest.approx(-6)
    assert result.ending_equity == pytest.approx(9994)
    assert result.skipped_daily_loss > 0
    deals = [NS(magic=cfg.magic, entry=0, profit=0, commission=-3),
             NS(magic=cfg.magic, entry=1, profit=0, commission=-3)]
    monkeypatch.setattr(m, "mt5", NS(history_deals_get=lambda *args: deals))
    assert m.MT5Adapter().realized_pnl_today({cfg.magic}, start) == pytest.approx(result.net_pnl_money)
