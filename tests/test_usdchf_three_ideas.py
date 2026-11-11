"""Exercise the three hypotheses using synthetic data, with no broker access."""
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

import pytest

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import HistoricalData
from src.engine import orchestrator as live
from src.execution.mt5_adapter import MT5Adapter
from src.risk.sizing import SymbolTradeInfo
from src.services.config import AppConfig, load_config
from src.strategy.liquidity import SweepSignal
from src.tools import backtest_mt5 as replay
from src.tools import research_usdchf_three_ideas as study


@pytest.fixture(autouse=True)
def no_broker(monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("Broker access or trades forbidden")
    for name in ("initialize", "send_market_order_with_price_protection", "send_market_order_with_fallback",
                 "close_position_market_with_fallback", "modify_position_protection"):
        monkeypatch.setattr(MT5Adapter, name, forbidden)


@pytest.fixture
def app(tmp_path):
    app = load_config(tmp_path / "defaults.json")
    cfg = replace(app.symbols[0], symbol="USDCHF", timeframe="M30", cisd_timeframe="M1",
                  cisd_lookback_bars=300, max_spread_pips=1.8, sl_pips=20, max_lot=.05,
                  strategy_mode="trend_micro_burst_v2", confirmation_mode="none",
                  allowed_sessions_utc=(), use_bias_filter=False, use_order_block_filter=False,
                  cooldown_sec=0)
    runtime = replace(app.runtime, dry_run=True, trailing_stop_mode="r_multiple", trailing_activation_r=1,
                      trailing_gap_r=1, trailing_remove_tp_on_activation=True, push_notifications_enabled=False,
                      max_profit_per_trade_usd=0)
    return AppConfig(runtime, (cfg,))


def bar(time, price=1.1, **kwargs):
    return dict(time=time, open=price, high=price+.00001, low=price-.00001, close=price,
                spread=10, tick_volume=100) | kwargs


def test_only_declared_fields_change_and_all_risk_guards_stay_identical(app):
    base = app.symbols[0]
    models = study.variants(base)
    assert len(models) == 7
    expected = {"baseline": set(), "buy_only": {"trade_side_filter"}, "sell_only": {"trade_side_filter"},
                "spread_1_2": {"max_spread_pips"}, "spread_0_9": {"max_spread_pips"},
                "trail_gap_0_75": {"trailing_gap_r"}, "trail_gap_0_5": {"trailing_gap_r"}}
    for model in models:
        changed = {key for key, value in asdict(base).items() if asdict(model.settings)[key] != value}
        assert changed == expected[model.name]
        assert model.settings.sl_pips == 20
        assert model.settings.risk_pct == .1
        assert model.settings.max_lot == .05
        assert model.settings.one_position_per_symbol
        assert not model.settings.ignore_portfolio_cap
        mode, activation, gap, remove_tp = live.effective_trailing_settings(model.settings, app.runtime)
        assert mode == "r_multiple" and activation == 1 and gap <= 1 and remove_tp


@pytest.mark.parametrize("model_name,side,expected", [
    ("buy_only", "BUY", True), ("buy_only", "SELL", False),
    ("sell_only", "SELL", True), ("sell_only", "BUY", False),
])
def test_direction_filter_replays_full_strategy_and_matches_live(app, monkeypatch, model_name, side, expected):
    cfg = next(v.settings for v in study.variants(app.symbols[0]) if v.name == model_name)
    assert live.trade_side_allowed(cfg, side) == expected
    assert replay._side_allowed(cfg.trade_side_filter, side) == expected
    monkeypatch.setattr(replay, "_detect_signal_for_cfg", lambda cfg, pip, rates, *args:
                        (SweepSignal(side, 1., rates[-2]["time"]), [], None))
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    stamp = int(start.timestamp())
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)
    history = HistoricalData("USDCHF", info, {"M1": [bar(stamp+i*60) for i in range(660)]})
    result, trades = replay.run_backtest(AppConfig(app.runtime, (cfg,)), cfg, start, start+timedelta(hours=10),
                                   initial_equity=10000, costs=ExecutionCosts(), history=history, end_exclusive=True)
    assert bool(trades) == expected
    assert result.side_mode == cfg.trade_side_filter
    assert all(t.side == side and t.commission_cost_money > 0 and t.slippage_cost_money > 0 for t in trades)


@pytest.mark.parametrize("name,points,expected", [
    ("spread_1_2", 12, True), ("spread_1_2", 13, False),
    ("spread_0_9", 9, True), ("spread_0_9", 10, False),
])
def test_spread_gate_uses_observed_spread_and_keeps_all_execution_costs(app, monkeypatch, name, points, expected):
    cfg = next(v.settings for v in study.variants(app.symbols[0]) if v.name == name)
    monkeypatch.setattr(replay, "_detect_signal_for_cfg", lambda cfg, pip, rates, *args:
                        (SweepSignal("BUY", 1., rates[-2]["time"]), [], None))
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    stamp = int(start.timestamp())
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)
    history = HistoricalData("USDCHF", info, {"M1": [bar(stamp+i*60, spread=points) for i in range(660)]})
    # A large fallback proves the gate reads observed points, not an assumed cheap spread.
    costs = ExecutionCosts("historical", 10, 3.5, .2)
    _, trades = replay.run_backtest(AppConfig(app.runtime, (cfg,)), cfg, start, start+timedelta(hours=10),
                                   initial_equity=10000, costs=costs, history=history, end_exclusive=True)
    assert bool(trades) == expected
    for trade in trades:
        assert trade.pnl_money < 0  # Flat prices still incur every execution cost.
        assert trade.gross_pnl_money == pytest.approx(0, abs=1e-8)
        assert trade.gross_pnl_money-trade.spread_cost_money-trade.commission_cost_money-trade.slippage_cost_money == pytest.approx(trade.pnl_money)


@pytest.mark.parametrize("side", ["BUY", "SELL"])
@pytest.mark.parametrize("name", ["trail_gap_0_75", "trail_gap_0_5"])
def test_tighter_exit_uses_shared_live_trailing_math_and_immutable_initial_r(app, side, name):
    cfg = next(v.settings for v in study.variants(app.symbols[0]) if v.name == name)
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)
    costs = ExecutionCosts("fixed", 1, 3.5, .2)
    trade = replay._build_entry_trade(cfg, app.runtime, info, 10000, side, 1000, 1.1, "key", "test",
                                      costs=costs, spread_pips=1)
    assert trade is not None
    risk = abs(trade.entry_price-trade.initial_sl)
    original_sl, original_risk = trade.initial_sl, trade.risk_money
    # Use the correct executable side for the short's quote.
    quote = trade.entry_price + (1.2*risk if side == "BUY" else -1.2*risk)
    bid = quote-(.0001 if side == "SELL" else 0)
    expected = live.compute_r_multiple_trailing_stop(side=side, open_price=trade.entry_price,
        current_exit_price_value=quote, current_sl=trade.sl, risk_distance_price=risk,
        activation_r=1, gap_r=cfg.trailing_gap_r)
    updated, closed = replay._apply_open_trade_bar(cfg, app.runtime, trade, bar(1060, bid), info)
    assert closed is None
    assert updated.sl == pytest.approx(expected)
    assert updated.initial_sl == original_sl and updated.risk_money == original_risk
    assert updated.tp == 0
    # A subsequent retracement cannot move the protective stop further away.
    old_sl = updated.sl
    _, closed = replay._apply_open_trade_bar(cfg, app.runtime, updated, bar(1120, bid), info)
    assert closed is None and updated.sl == old_sl


def metrics(net=10, dd=5, trades=30):
    return {"net_pnl": net, "max_realized_drawdown": dd, "trades": trades}


def test_training_ranks_profit_without_relaxing_sample_or_drawdown_constraints():
    values = {"baseline": metrics(), "best": metrics(30, 6), "safer": metrics(20, 1),
              "tiny": metrics(100, 1, 19), "risky": metrics(200, 6.26)}
    selected, reasons = study.select_profit(values, ["best", "safer", "tiny", "risky"])
    assert selected == "best"
    assert reasons["tiny"] and reasons["risky"]
    assert study.select_profit({"baseline": metrics(), "tie": metrics()}, ["tie"])[0] == "baseline"


@pytest.mark.parametrize("spread,limit,allowed", [(1.2000000000000002, 1.2, True),
    (1.20001, 1.2, False), (float("nan"), 1.2, False), (float("inf"), 1.2, False),
    (-1, 1.2, False), (1, float("nan"), False), (0, 0, True)])
def test_live_and_replay_spread_gate_share_finite_boundary_semantics(spread, limit, allowed):
    assert live.spread_within_limit is replay.spread_within_limit
    assert live.spread_within_limit(spread, limit) == allowed


def test_fixed_nomination_never_uses_later_training_or_test_winners():
    training = {i: {"baseline": metrics(), "good": metrics(20, 6), "later": metrics(1)} for i in range(1, 13)}
    for i in range(7, 13):
        training[i]["later"] = metrics(100000, 0)
    assert study.select_fixed(training, ["good", "later"])[0] == "good"
    for i in (1, 2, 3):
        training[i]["good"] = metrics(1000, 1, 19)
    assert study.select_fixed(training, ["good", "later"])[0] == "baseline"


def test_registration_preserves_original_time_and_refuses_protocol_changes(tmp_path):
    original = {"registered_at_utc": "first", "costs": {"commission": 3.5}, "hypotheses": ["a", "b"]}
    study.register(original, tmp_path)
    assert study.register(dict(original, registered_at_utc="second"), tmp_path) == original
    with pytest.raises(ValueError, match="Frozen study differs"):
        study.register(dict(original, costs={"commission": 0}), tmp_path)


def test_registration_normalizes_dataclass_tuples_without_changing_protocol(tmp_path):
    plan = {"registered_at_utc": "first", "sessions": ("05:00-12:00", "13:00-20:00")}
    study.register(plan, tmp_path)
    assert study.register(plan, tmp_path)["sessions"] == list(plan["sessions"])
