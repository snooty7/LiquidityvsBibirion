"""New entries must be causal, structurally protected and identical under replay caching."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

import pytest

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import HistoricalData
from src.backtesting.scalping import ScalpPolicy
from src.backtesting.swaps import SwapModel
from src.execution.mt5_adapter import MT5Adapter
from src.risk.sizing import SymbolTradeInfo
from src.services.config import AppConfig, load_config
from src.strategy.fast_scalp import MODELS, ScalpEntry, ScalpFeatures, ScalpSignalProvider
from src.strategy.liquidity import SweepSignal
from src.tools.backtest_mt5 import run_backtest


def bars_for(model, side="BUY"):
    start = int(datetime(2026, 1, 5, 6, tzinfo=timezone.utc).timestamp())
    m5 = [dict(time=start+i*300, open=1.1+i*.00002, close=1.1+i*.00002+.00001,
        high=1.1+i*.00002+.00003, low=1.1+i*.00002-.00003) for i in range(80)]
    m1 = [dict(time=start+60*300+i*60, open=1.1014, close=1.1014,
               high=1.10155, low=1.10125) for i in range(31)]
    if model == "m1_sweep_reclaim":
        m1[-2].update(open=1.10135, low=1.1006, close=1.10145, high=1.10155)
        m1[-1].update(open=1.10145, low=1.1014, high=1.102, close=1.10195)
    elif model == "m1_ema_reclaim":
        m1[-2].update(open=1.1014, low=1.1005, close=1.1010, high=1.1015)
        m1[-1].update(open=1.10105, low=1.10095, high=1.1019, close=1.1018)
    else:
        m5[65].update(open=1.1013, low=1.1005, close=1.1015, high=1.1016)
        m1[-1].update(open=1.1014, low=1.1013, high=1.1019, close=1.1018)
    if side == "SELL":
        for b in m1+m5:
            b.update(open=2.2-b["open"], close=2.2-b["close"], high=2.2-b["low"], low=2.2-b["high"])
    return m1, m5


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_each_new_entry_has_its_own_valid_closed_bar_pattern(model, side):
    m1, m5 = bars_for(model, side)
    signal = ScalpFeatures(m1, m5, .0001).at(len(m1)-1, model)
    assert signal is not None
    assert signal.signal.side == side
    direction = 1 if side == "BUY" else -1
    distance = direction*(m1[-1]["close"]-signal.stop_price)/.0001
    assert 6 <= distance <= 15
    assert signal.tp_r_multiple == 2 and signal.risk_pct_override == 0


@pytest.mark.parametrize("model", MODELS)
def test_appending_future_m1_and_forming_m5_spikes_cannot_change_an_earlier_entry(model):
    m1, m5 = bars_for(model)
    index = len(m1)-1
    before = ScalpFeatures(m1, m5, .0001).at(index, model)
    assert before is not None
    future1, future5 = deepcopy(m1), deepcopy(m5)
    future1.append(dict(time=m1[-1]["time"]+60, open=1.5, high=1.6, low=1.4, close=1.55))
    for b in future5:
        if b["time"]+300 > m1[-1]["time"]+60:
            b.update(open=1.5, high=1.6, low=1.4, close=1.55)
    assert ScalpFeatures(future1, future5, .0001).at(index, model) == before


def test_m5_setup_must_close_before_its_m1_confirmation():
    m1, m5 = bars_for("m5_sweep_m1_confirm")
    m1[-1]["time"] -= 60  # Its close now coincides with, rather than follows, setup close.
    assert ScalpFeatures(m1, m5, .0001).at(len(m1)-1, "m5_sweep_m1_confirm") is None


def test_weak_displacement_and_unaffordable_structural_width_are_rejected():
    m1, m5 = bars_for("m1_sweep_reclaim")
    m1[-1]["open"] = m1[-1]["close"]
    assert ScalpFeatures(m1, m5, .0001).at(len(m1)-1, "m1_sweep_reclaim") is None
    m1, m5 = bars_for("m1_sweep_reclaim")
    m1[-2]["low"] = 1.095
    assert ScalpFeatures(m1, m5, .0001).at(len(m1)-1, "m1_sweep_reclaim") is None


def test_research_provider_requires_offline_history_before_any_broker_connection(tmp_path, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("Broker connection forbidden")
    monkeypatch.setattr(MT5Adapter, "initialize", forbidden)
    app = load_config(tmp_path/"defaults.json")
    now = datetime(2026, 1, 5, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="offline"):
        run_backtest(app, app.symbols[0], now, now+timedelta(days=1), initial_equity=10000,
                     signal_provider=ScalpSignalProvider({}))


def test_research_mode_cannot_fall_back_to_old_signals_without_a_provider(tmp_path):
    app = load_config(tmp_path/"defaults.json")
    cfg = replace(app.symbols[0], strategy_mode="fast_scalp_research")
    now = datetime(2026, 1, 5, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="provider"):
        run_backtest(app, cfg, now, now+timedelta(days=1), initial_equity=10000)


def test_m1_provider_rejects_a_different_decision_clock(tmp_path):
    cfg = load_config(tmp_path/"defaults.json").symbols[0]
    assert cfg.timeframe != "M1"
    with pytest.raises(ValueError, match="M1"):
        ScalpSignalProvider({})(cfg, .0001, [], [], [])


def test_new_entry_configuration_keeps_existing_risk_and_nomination_holds_cash(tmp_path):
    from src.tools.research_fast_scalp_entries import configurations_for_pair, nominate
    base = replace(load_config(tmp_path/"defaults.json").symbols[0], risk_pct=.75, max_lot=.5,
                   sl_pips=20, rr=2, cooldown_sec=3600, trailing_activation_r=1.5)
    cfg = configurations_for_pair(base, "GBPUSD")
    assert cfg.symbol == "GBPUSD" and cfg.timeframe == "M1" and cfg.bias_timeframe == "M5"
    for field in ("risk_pct", "max_lot", "sl_pips", "rr", "cooldown_sec", "trailing_activation_r"):
        assert getattr(cfg, field) == getattr(base, field)
    def row(net, flat=True):
        return {"metrics": {"trades": 3, "net_pnl": net}, "no_overnight_and_no_swap": flat,
                "account": {"m1_close_drawdown": 10}}
    assert nominate({"loser": row(-1), "financed": row(100, False)}) == (None, [])
    assert nominate({"candidate": row(1), "loser": row(-1)}) == ("candidate", ["candidate"])


@pytest.mark.parametrize("side,sign", [("BUY", 1), ("SELL", -1)])
def test_broker_ceiling_allows_requested_risk_budget_without_arbitrary_lot_increase(tmp_path, side, sign):
    from src.tools.research_fast_scalp_entries import configurations_for_pair
    from src.tools.backtest_mt5 import PendingSetupLite, _build_entry_trade
    from src.risk.sizing import calc_position_risk_money
    app = load_config(tmp_path/"defaults.json")
    base = replace(app.symbols[0], risk_pct=.75, max_lot=.5)
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, .9, .00001)
    cfg = configurations_for_pair(base, "EURUSD", info.volume_max)
    runtime = replace(app.runtime, max_total_open_risk_pct=.75)
    pending = PendingSetupLite("key", side, 1.1, 0, 60,
        context={"risk": {"sl_price": 1.1-sign*.0006, "tp_r_multiple": 2}})
    trade = _build_entry_trade(cfg, runtime, info, 10000, side, 0, 1.1, "key", "test", pending,
                               costs=ExecutionCosts(), spread_pips=.7)
    assert trade is not None and .5 < trade.volume <= info.volume_max
    risk = calc_position_risk_money(trade.entry_price, trade.sl, trade.volume, info)
    assert 74 <= risk <= 75
    assert cfg.risk_pct == .75 and trade.sl == pending.context["risk"]["sl_price"]


@pytest.mark.parametrize("side", ["BUY", "SELL"])
@pytest.mark.parametrize("exit_kind", ["final", "time", "daily", "stop"])
def test_cached_entry_schedule_preserves_risk_fees_time_exits_and_final_quote(tmp_path, monkeypatch, side, exit_kind):
    def forbidden(*a, **k):
        raise AssertionError("Broker or orders forbidden")
    monkeypatch.setattr(MT5Adapter, "initialize", forbidden)
    import MetaTrader5 as mt5
    monkeypatch.setattr(mt5, "order_send", forbidden)
    monkeypatch.setattr(mt5, "order_check", forbidden)
    app = load_config(tmp_path/"defaults.json")
    cfg = replace(app.symbols[0], timeframe="M1", bars=60, strategy_mode="fast_scalp_research",
        confirmation_mode="none", use_bias_filter=False, use_order_block_filter=False,
        bias_timeframe="M5", setup_timeframe="M5", allowed_sessions_utc=(),
        risk_pct=.75, max_lot=.5, sl_pips=20, rr=2, cooldown_sec=3600)
    app = AppConfig(replace(app.runtime, daily_loss_limit_usd=1 if exit_kind == "daily" else 150, max_total_open_risk_pct=.75,
        max_profit_per_trade_usd=0, trailing_stop_mode="off"), (cfg,))
    start = datetime(2026, 1, 5, 8, tzinfo=timezone.utc)
    ts = int(start.timestamp())
    rows = [dict(time=ts+i*60, open=1.1, high=1.100001, low=1.099999,
        close=1.1, spread=5, tick_volume=100) for i in range(-120, 121)]
    if exit_kind == "stop":
        next(b for b in rows if b["time"] == ts+300)["low" if side == "BUY" else "high"] = 1.098 if side == "BUY" else 1.102
    direction = 1 if side == "BUY" else -1
    entry = ScalpEntry(SweepSignal(side, 1.1, ts-60), 1.1-direction*.001, "test")
    provider = ScalpSignalProvider({ts: entry})
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)
    history = HistoricalData(cfg.symbol, info, {"M1": rows})
    kwargs = dict(initial_equity=10000, history=history, costs=ExecutionCosts(), swaps=SwapModel(-1, -1),
                  overnight_policy=ScalpPolicy(30), end_exclusive=True)
    end = start+timedelta(minutes=20 if exit_kind == "final" else 60)
    a, ta = run_backtest(app, cfg, start, end, signal_provider=provider, **kwargs)
    b, tb = run_backtest(app, cfg, start, end, signal_provider=lambda *args: provider(*args), **kwargs)
    assert [asdict(t) for t in ta] == [asdict(t) for t in tb]
    assert asdict(a) == asdict(b)
    assert len(ta) == 1
    assert ta[0].reason == {"final": "end_of_test", "time": "scalp_time_exit", "daily": "daily_loss_guard_close", "stop": "stop_loss"}[exit_kind]
    if exit_kind == "final":
        assert ta[0].exit_time_utc == end.isoformat()
    risk = abs(ta[0].entry_price-ta[0].sl_initial)/info.trade_tick_size*info.trade_tick_value*ta[0].volume
    assert risk <= 75 and ta[0].volume <= .5
    assert abs(ta[0].sl_initial-entry.stop_price) < 1e-12
