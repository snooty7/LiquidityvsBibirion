"""Adaptive safety/causality tests; real broker access is forbidden in every test."""
from dataclasses import asdict, replace
import json
import math

import pytest

from src.backtesting.history import HistoricalData, resample_m1
from src.risk.preflight import BrokerLimits, Exposure, aligned_correlation, check_entry, partial_close_volume
from src.risk.sizing import SymbolTradeInfo
from src.services.config import load_config
from src.strategy.adaptive.config import AdaptiveConfig, load_adaptive
from src.strategy.adaptive.context import snapshot
from src.strategy.adaptive.engine import evaluate
from src.strategy.adaptive.exits import decide_exit
from src.strategy.adaptive.ml_shadow import chronological_split, observe
from src.strategy.adaptive.models import Candle, FeatureObservation, Regime
from src.strategy.adaptive.regime import detect_regime
from src.strategy.adaptive.scoring import COMPONENTS, score_features
from src.strategy.adaptive.structure import analyze_structure


@pytest.fixture(autouse=True)
def no_broker(monkeypatch):
    from src.execution.mt5_adapter import MT5Adapter

    def forbidden(*args, **kwargs):
        raise AssertionError("Adaptive tests must not access MT5")
    for name in ("initialize", "send_market_order_with_price_protection", "send_market_order_with_fallback", "close_position_market_with_fallback", "modify_position_protection"):
        monkeypatch.setattr(MT5Adapter, name, forbidden)


@pytest.fixture
def info():
    return SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)


def bars(count=120, step=300, trend=.00001):
    return [dict(time=index*step, open=1.1+index*trend, high=1.1002+index*trend,
                 low=1.0998+index*trend, close=1.10005+index*trend, tick_volume=100)
            for index in range(count)]


def candles(rows):
    return tuple(Candle(**row) for row in rows)


def preflight(info, **overrides):
    args = dict(side="BUY", symbol="EURUSD", price=1.1, sl=1.099, tp=1.102,
                equity=10000, risk_pct=.1, authorized_risk_pct=.1, info=info,
                limits=BrokerLimits(.0001, 0, .00001), max_lot=1, min_lot=0,
                spread_pips=1, max_spread_pips=2, quote_time=100, decision_time=101,
                max_quote_age=3, realized_today=0, daily_limit=50, positions=(),
                portfolio_cap_pct=.5, max_positions=4, currency_cap_pct=.5,
                correlation_cap_pct=.5, correlations={}, min_rr=1.5,
                research=True)
    return check_entry(**(args | overrides))


def test_defaults_do_not_change_existing_configuration(tmp_path):
    app = load_config(tmp_path/"absent.json")
    assert app.adaptive == AdaptiveConfig()
    assert not app.adaptive.enabled and not app.adaptive.ml_shadow
    assert app.runtime.per_trade_loss_guard_mode == "position_risk"
    assert app.runtime.per_trade_loss_risk_multiple == 1


@pytest.mark.parametrize("values", [dict(dynamic_leverage=True), dict(hedging=True), dict(enabled="false"),
                                      dict(weights=[.3]*5), dict(score_threshold=float("nan")),
                                      dict(context_timeframes=["M1"]), dict(lookback=2), dict(typo=1)])
def test_invalid_configuration_is_rejected(values):
    with pytest.raises((ValueError, TypeError)):
        load_adaptive(values)


def test_portfolio_bypass_cannot_be_enabled_for_adaptive(tmp_path):
    path = tmp_path/"settings.json"
    path.write_text(json.dumps({"adaptive": {"enabled": True}, "symbols": [{"symbol": "EURUSD", "ignore_portfolio_cap": True}]}))
    with pytest.raises(ValueError, match="ignore_portfolio_cap"):
        load_config(path)


def test_forming_and_future_bars_cannot_change_observations():
    config = AdaptiveConfig(enabled=True, context_timeframes=("H1",))
    rates = {"M5": bars(1500), "H1": bars(130, 3600)}
    time = 120*3600
    first = snapshot("EURUSD", time, rates, config)
    future = {tf: [row if row["time"]+step <= time else row | {"close": float("nan")}
                   for row in rows] for (tf, rows), step in zip(rates.items(), (300, 3600))}
    second = snapshot("EURUSD", time, future, config)
    assert first == second and not first.reasons
    assert all(bar.time+dict(M5=300, H1=3600)[tf] <= time for tf, rows in first.series for bar in rows)


@pytest.mark.parametrize("damage", ["missing", "gap", "stale", "bad_price"])
def test_bad_context_blocks_proposals(damage):
    config = AdaptiveConfig(enabled=True, context_timeframes=("H1",))
    rates = {"M5": bars(1500), "H1": bars(125, 3600)}
    if damage == "missing":
        rates.pop("H1")
    elif damage == "gap":
        rates["H1"].pop(-10)
    elif damage == "stale":
        rates["H1"] = rates["H1"][:-10]
    else:
        rates["H1"][-10]["low"] = -1
    context = snapshot("EURUSD", 125*3600, rates, config)
    result = evaluate(context, config, pip=.0001, tick_size=.00001, entry_price=1.1)
    assert context.reasons and result.proposal is None


def test_d1_utc_discards_incomplete_fx_sessions():
    complete = resample_m1(bars(1440, 60), "D1")
    assert len(complete) == 1 and complete[0]["time"] == 0
    assert resample_m1(bars(1439, 60), "D1") == []
    gap = bars(1440, 60)
    gap.pop(100)
    assert resample_m1(gap, "D1") == []


def test_missing_flow_keeps_fixed_denominator_and_is_auditable():
    config = AdaptiveConfig()
    observations = tuple(FeatureObservation(name, 1, "test", 100) for name in COMPONENTS[:-1])
    result = score_features(observations, config, 100)
    assert result.score == pytest.approx(.9)
    assert result.observations[-1].value is None
    assert "required_feature_unavailable:order_flow" in score_features(observations, replace(config, require_order_flow=True), 100).reasons
    with pytest.raises(ValueError):
        score_features((FeatureObservation("sweep", 1.1, "bad", 100),), config, 100)
    with pytest.raises(ValueError):
        score_features((FeatureObservation("sweep", 1, "future", 101),), config, 100)


def test_regimes_and_extreme_volatility():
    config = AdaptiveConfig(high_atr_percentile=1.0)
    up = detect_regime(candles(bars(120, trend=.0002)), config)
    down = detect_regime(candles(bars(120, trend=-.0002)), config)
    flat = detect_regime(candles(bars(120, trend=0)), config)
    extreme = detect_regime(candles(bars(120, trend=.0002)), replace(config, high_realized_volatility=.000000001))
    assert up.regime == Regime.TRENDING_BULLISH
    assert down.regime == Regime.TRENDING_BEARISH
    assert flat.regime == Regime.RANGING
    assert extreme.regime == Regime.HIGH_VOLATILITY
    assert detect_regime((), config).regime == Regime.UNCERTAIN


def test_pivot_cannot_be_swept_before_confirmation_and_zone_lifecycle():
    config = AdaptiveConfig(pivot_length=2)
    rows = [Candle(i*300, 10, high, 8, 9) for i, high in enumerate((10, 11, 15, 12, 11, 16))]
    structure = analyze_structure(tuple(rows), config, 1, .1)
    assert any(event.kind == "SWEEP" and event.price == 15 and event.available_at == 1800 for event in structure.events)
    earlier = analyze_structure(tuple(rows[:4]), config, 1, .1)
    assert 15 not in earlier.liquidity
    gap_rows = (Candle(0, 10, 11, 9, 10), Candle(300, 12, 13, 11, 12), Candle(600, 14, 15, 13, 14))
    active = analyze_structure(gap_rows, config, 1, .1)
    assert active.zones[0].status == "active" and active.zones[0].available_at == 900
    touched = analyze_structure(gap_rows+(Candle(900, 14, 14, 12, 13),), config, 1, .1)
    assert touched.zones[0].status == "mitigated"
    invalid = analyze_structure(gap_rows+(Candle(900, 12, 13, 9, 10),), config, 1, .1)
    assert invalid.zones[0].status == "invalidated"


@pytest.mark.parametrize("overrides,reason", [
    ({"spread_pips": 20}, "spread_limit"), ({"quote_time": 90}, "stale_or_future_quote"),
    ({"quote_time": 102}, "stale_or_future_quote"), ({"realized_today": -50}, "daily_loss_limit"),
    ({"realized_today": float("nan")}, "nonfinite_preflight"),
    ({"risk_pct": .2}, "invalid_protection_or_budget"),
    ({"sl": 1.11}, "invalid_protection_or_budget"),
    ({"limits": BrokerLimits(.002, 0, .00001)}, "broker_stop_distance"),
    ({"sl": 1.099001}, "price_off_tick"), ({"research": False}, "margin_unverified"),
    ({"tp": 1.101}, "net_reward_risk"),
])
def test_preflight_fails_closed(info, overrides, reason):
    result = preflight(info, **overrides)
    assert not result.allowed and reason in result.reasons and result.volume == 0


def test_volume_budget_unknown_and_deduplicated_exposure(info):
    result = preflight(info)
    assert result.allowed and result.risk_money <= 10 + 1e-9
    assert preflight(info, min_lot=1).allowed is False
    exposure = Exposure(1, "EURUSD", "BUY", 10)
    assert preflight(info, positions=(exposure, exposure), max_positions=2).allowed
    assert "portfolio_risk_limit" in preflight(info, positions=(replace(exposure, risk_money=50),)).reasons
    assert "unknown_position_exposure" in preflight(info, positions=(replace(exposure, risk_money=float("inf")),)).reasons
    other = Exposure(2, "GBPUSD", "SELL", 10)
    assert "correlation_unavailable:GBPUSD" in preflight(info, positions=(other,)).reasons
    assert preflight(info, positions=(other,), correlations={"GBPUSD": -.9}).allowed
    assert "correlation_exposure_limit" in preflight(info, positions=(other,), correlations={"GBPUSD": -.9}, correlation_cap_pct=.1).reasons


def test_correlation_alignment_excludes_future_returns():
    returns = {i: math.sin(i) for i in range(50)}
    other = {i: -math.sin(i) for i in range(50)}
    assert aligned_correlation(returns, other, decision_time=35) == pytest.approx(-1)
    assert aligned_correlation(returns, other, decision_time=20) is None
    assert aligned_correlation(returns, {i: 1 for i in returns}, decision_time=49) is None


@pytest.mark.parametrize("side,entry,initial,current,price", [("BUY", 1.1, 1.099, 1.1, 1.103), ("SELL", 1.1, 1.101, 1.1, 1.097)])
def test_exits_only_tighten_and_partials_are_one_shot(info, side, entry, initial, current, price):
    config = AdaptiveConfig(break_even_r=1, trailing_activation_r=2, partial_exit_r=2)
    result = decide_exit(side=side, entry=entry, initial_stop=initial, current_stop=current,
                         exit_price=price, volume=.1, info=info, config=config)
    assert result.stop > current if side == "BUY" else result.stop < current
    assert result.close_volume == .05 and result.milestone == "partial_1"
    again = decide_exit(side=side, entry=entry, initial_stop=initial, current_stop=result.stop,
                        exit_price=price, volume=.05, info=info, config=config, completed=frozenset({"partial_1"}))
    assert again.stop is None and again.close_volume == 0
    assert partial_close_volume(.01, .5, info) == 0


def test_shadow_never_invents_probability_and_splits_purge_labels():
    assert observe((1,)).status == "model_unavailable"
    assert observe((1,), predictor=lambda _: .7, model_digest="fixed").probability == .7
    assert observe((1,), predictor=lambda _: float("nan"), model_digest="fixed").probability is None
    result = chronological_split([dict(time=i, label_available_at=i+4) for i in range(30)], 10, 20, 30, 2)
    assert all(row["label_available_at"] < 10 for row in result["train"])
    assert all(row["time"] >= 12 and row["label_available_at"] < 20 for row in result["validation"])
    assert all(row["time"] >= 22 and row["label_available_at"] < 30 for row in result["test"])


def test_valid_proposal_duplicate_and_conflicting_timeframes(monkeypatch):
    from src.strategy.adaptive.models import RegimeResult, StructureContext, StructureEvent, Zone
    from src.strategy.adaptive import engine

    config = AdaptiveConfig(enabled=True, context_timeframes=("H1",), score_threshold=.6)
    rates = {"M5": bars(1500), "H1": bars(125, 3600)}
    context = snapshot("EURUSD", 125*3600, rates, config)
    regime = RegimeResult(Regime.TRENDING_BULLISH, .0001, 40, .5, .0001, 1, "fixture")
    sweep = StructureEvent("SWEEP", "BUY", 1.1, 100, context.bars("M5")[-3].time+300, 1)
    broken = StructureEvent("BOS", "BUY", 1.11, 200, context.bars("M5")[-1].time+300, 1)
    structure = StructureContext((sweep, broken), (Zone("FVG", "BUY", 1.1000, 1.1002, 300, "active"),), (1.12,), 1.09, 1.12)
    monkeypatch.setattr(engine, "detect_regime", lambda *_: regime)
    monkeypatch.setattr(engine, "analyze_structure", lambda *_: structure)
    monkeypatch.setattr(engine, "directions", lambda *_: (("H1", "BUY"),))
    result = evaluate(context, config, pip=.0001, tick_size=.00001, entry_price=1.115, candidate_side="BUY")
    assert result.proposal is not None and result.proposal.sl < 1.115 < result.proposal.tp
    duplicate = evaluate(context, config, pip=.0001, tick_size=.00001, entry_price=1.115,
                         candidate_side="BUY", seen_keys=frozenset({result.proposal.key}))
    assert duplicate.proposal is None and "duplicate_signal" in duplicate.reasons
    monkeypatch.setattr(engine, "directions", lambda *_: (("H1", "SELL"),))
    conflict = evaluate(context, config, pip=.0001, tick_size=.00001, entry_price=1.115, candidate_side="BUY")
    assert conflict.proposal is None and "timeframe_conflict" in conflict.reasons


def test_partial_replay_costs_and_residual_risk_reconcile(info):
    from src.backtesting.adaptive import AdaptiveReplayPolicy
    from src.backtesting.costs import ExecutionCosts
    from src.tools.backtest_mt5 import OpenTrade

    history = HistoricalData("EURUSD", info, {"M1": []})
    policy = AdaptiveReplayPolicy(history, AdaptiveConfig(enabled=True, partial_exit_r=1), "adaptive")
    trade = OpenTrade("BUY", 0, 1.1, 1.099, 1.11, .1, 10, "signal", "test", 1.099, 1.11,
                      entry_commission_money=.35, exit_commission_money=.35,
                      costs=ExecutionCosts("fixed", 1, 3.5, .2), entry_spread_cost_money=1,
                      entry_slippage_cost_money=.2)
    closed = policy.exit(trade, dict(time=60, close=1.102), info)
    assert len(closed) == 1 and closed[0].reason == "adaptive_partial"
    assert trade.volume == pytest.approx(.05) and trade.risk_money == pytest.approx(5)
    assert trade.entry_commission_money+closed[0].commission_cost_money/2 == pytest.approx(.35)
    assert closed[0].pnl_money == pytest.approx(9.55)
    assert policy.exit(trade, dict(time=120, close=1.103), info) == []


def test_dashboard_observations_disabled_have_no_proposal(info):
    from dashboard.adaptive import build_observation
    payload = build_observation(symbol="EURUSD", decision_time=100, rates={}, config=AdaptiveConfig(),
                                info=info, equity=10000, risk_pct=.1, min_lot=0, max_lot=1)
    assert payload["evaluation"]["proposal"] is None
    assert "adaptive_disabled" in payload["evaluation"]["reasons"]
    assert payload["shadow"] is None
    json.dumps(payload, allow_nan=False)


def test_dashboard_default_has_no_adaptive_calls(tmp_path):
    from dashboard.server import DashboardState
    from threading import Lock
    from types import SimpleNamespace

    calls = []
    state = DashboardState.__new__(DashboardState)
    state.app_config = load_config(tmp_path/"defaults.json")
    state.symbols = ["EURUSD"]
    state.csv_path = tmp_path/"missing.csv"
    state._lock = Lock()
    state.adapter = SimpleNamespace(copy_rates=lambda symbol, tf, count: calls.append(tf) or [])
    payload = state.build_snapshot("EURUSD")
    assert "adaptive" not in payload and calls == ["M1", "M5", "M15", "M30"]


def test_dashboard_enabled_observation_uses_fake_quotes_only(tmp_path, info):
    from dashboard.server import DashboardState
    from threading import Lock
    from types import SimpleNamespace

    state = DashboardState.__new__(DashboardState)
    state.app_config = replace(load_config(tmp_path/"defaults.json"), adaptive=AdaptiveConfig(enabled=True, ml_shadow=True))
    state.symbols, state.csv_path, state._lock = ["EURUSD"], tmp_path/"missing.csv", Lock()
    state.adaptive_comparison = [{"arm": "baseline", "status": "complete"}]
    state.adapter = SimpleNamespace(copy_rates=lambda *args: [], symbol_info=lambda *_: SimpleNamespace(**asdict(info)), account_equity=lambda: 10000)
    payload = state.build_snapshot("EURUSD")
    assert payload["adaptive"]["status"] == "observation_only_no_live_route"
    assert payload["adaptive"]["shadow"]["status"] == "model_unavailable"
    assert payload["adaptive"]["comparison"][0]["arm"] == "baseline"


def test_bad_timestamp_is_explicit_unavailable():
    context = snapshot("EURUSD", 1000, {"M5": [{"time": "bad"}]}, AdaptiveConfig())
    assert "M5:invalid_timestamp" in context.reasons


def test_currency_and_concentration_fail_closed(info):
    assert "currency_mapping_unavailable" in preflight(info, symbol="BTCUSD").reasons
    assert "currency_limit:USD" in preflight(info, positions=(Exposure(1, "GBPUSD", "SELL", 45),), correlations={"GBPUSD": .1}).reasons


def test_weekend_gap_requires_explicit_policy():
    from datetime import datetime, timezone
    monday = int(datetime(2026, 1, 12, tzinfo=timezone.utc).timestamp())
    # 100 daily bars with Saturdays/Sundays omitted, matching explicit UTC FX research.
    rows = []
    for index in range(150):
        timestamp = monday-index*86400
        if datetime.fromtimestamp(timestamp, timezone.utc).weekday() < 5:
            rows.append(dict(time=timestamp, open=1.1, high=1.2, low=1, close=1.1))
    rows.reverse()
    config = AdaptiveConfig(entry_timeframe="H4", context_timeframes=("D1",))
    first = snapshot("EURUSD", monday+86400, {"D1": rows}, config)
    second = snapshot("EURUSD", monday+86400, {"D1": rows}, replace(config, allow_utc_weekend_gaps=True))
    assert any(reason.startswith("D1:") for reason in first.reasons)
    assert not any(reason.startswith("D1:") for reason in second.reasons)
