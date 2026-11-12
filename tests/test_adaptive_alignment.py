"""Controlled causal contracts, independent of historical profits or trade counts."""
from dataclasses import replace

import pytest

from src.strategy.adaptive.alignment import align_signal
from src.strategy.adaptive.config import AdaptiveConfig
from src.strategy.adaptive.context import snapshot
from src.strategy.adaptive.engine import evaluate
from src.strategy.adaptive.models import Candle, MarketSnapshot, Regime, RegimeResult, SignalAnchor
from src.strategy.adaptive.structure import analyze_structure


@pytest.fixture(autouse=True)
def no_broker(monkeypatch):
    from src.execution.mt5_adapter import MT5Adapter
    def forbidden(*args, **kwargs):
        raise AssertionError("Alignment tests must remain offline")
    for name in ("initialize", "send_market_order_with_price_protection", "send_market_order_with_fallback",
                 "close_position_market_with_fallback", "modify_position_protection"):
        monkeypatch.setattr(MT5Adapter, name, forbidden)


def fixture():
    decision = 1_800_000
    rows = [Candle(decision+(i-600)*300, 1.1, 1.1002, 1.0998, 1.10005) for i in range(600)]
    rows[560] = replace(rows[560], high=1.106)  # untouched upside liquidity
    rows[570] = replace(rows[570], low=1.099)  # original, confirmed sell-side level
    rows[596] = replace(rows[596], open=1.0999, low=1.0984, close=1.1)
    for i in range(597, 600):
        rows[i] = replace(rows[i], open=1.1004, high=1.1006, close=1.10045)
    lower = [Candle(decision+(i-120)*60, 1.1, 1.10005, 1.09995, 1.1) for i in range(120)]
    available = rows[596].time+300
    for i, row in enumerate(lower):
        if row.time == available+240:
            lower[i] = Candle(row.time, 1.1, 1.1005, 1.09995, 1.10045)
        elif row.time > available+240:
            lower[i] = Candle(row.time, 1.10045, 1.10055, 1.10035, 1.10045)
    context = MarketSnapshot("EURUSD", decision, (("M5", tuple(rows)), ("M1", tuple(lower))), "controlled")
    anchor = SignalAnchor("EURUSD:92001", "BUY", 1.099, rows[596].time, decision+300,
                          "M5", "M1", "sweep_displacement_mss", 5, .00003, 12, 1.25,
                          .00005, 4, .55, 1.8)
    return context, anchor, AdaptiveConfig(enabled=True)


def test_exact_m5_sweep_gets_real_m1_break_without_a_second_m5_break():
    context, anchor, config = fixture()
    result = align_signal(context, anchor, config)
    assert not result.reasons and result.sweep and result.confirmation
    assert result.sweep.timeframe == "M5" and result.sweep.price == anchor.level
    assert result.confirmation.timeframe == "M1"
    assert result.confirmation.available_at == anchor.candle_time+300+300
    assert result.confirmation.strength > 1  # M1 normalization, not the M5 ATR
    structure = analyze_structure(context.bars("M5")[-100:], config, .0005, .0001)
    assert not any(event.kind in {"BOS", "MSS"} and event.side == "BUY" and event.available_at > result.sweep.available_at for event in structure.events)


def test_engine_uses_anchor_even_when_latest_independent_sweep_is_different(monkeypatch):
    from src.strategy.adaptive import engine
    context, anchor, config = fixture()
    monkeypatch.setattr(engine, "detect_regime", lambda *_: RegimeResult(Regime.RANGING, .0005, 10, .5, .001, 0, "controlled_regime"))
    monkeypatch.setattr(engine, "directions", lambda *_: (("H1", "BUY"), ("H4", "BUY")))
    result = evaluate(context, config, pip=.0001, tick_size=.00001, entry_price=1.10045,
                      candidate_side="BUY", anchor=anchor)
    assert result.proposal and result.score.score >= config.score_threshold
    assert config.score_threshold == .65 and config.weights == (.3, .25, .2, .15, .1)
    assert result.proposal.sl < 1.0984 and result.proposal.tp == pytest.approx(1.106)
    duplicate = evaluate(context, config, pip=.0001, tick_size=.00001, entry_price=1.10045,
                         candidate_side="BUY", anchor=anchor, seen_keys=frozenset({result.proposal.key}))
    assert duplicate.proposal is None and "duplicate_signal" in duplicate.reasons


@pytest.mark.parametrize("change,reason", [
    ({"level": 1.0989}, "anchor_level_not_confirmed"),
    ({"candle_time": 1_800_000}, "anchor_not_closed"),
    ({"expires_at": 1_800_000}, "anchor_expired"),
    ({"signal_timeframe": "M15"}, "anchor_identity_mismatch"),
    ({"confirmation_mode": "none"}, "anchor_confirmation_mode_unsupported"),
])
def test_wrong_or_stale_anchor_never_falls_back_to_another_sweep(change, reason):
    context, anchor, config = fixture()
    result = align_signal(context, replace(anchor, **change), config)
    assert reason in result.reasons and result.confirmation is None


def test_previously_taken_liquidity_is_not_resurrected():
    context, anchor, config = fixture()
    rows = list(context.bars("M5"))
    rows[580] = replace(rows[580], low=1.0988)
    context = replace(context, series=(("M5", tuple(rows)), ("M1", context.bars("M1"))))
    result = align_signal(context, anchor, config)
    assert result.sweep is None and "anchor_liquidity_already_consumed" in result.reasons


def test_break_before_sweep_close_is_not_post_sweep_confirmation():
    context, anchor, config = fixture()
    lower = [replace(row, open=1.1, high=1.10005, low=1.09995, close=1.1) for row in context.bars("M1")]
    before = anchor.candle_time+240
    lower = [Candle(row.time, 1.1, 1.1005, 1.09995, 1.10045) if row.time == before else row for row in lower]
    context = replace(context, series=(("M5", context.bars("M5")), ("M1", tuple(lower))))
    result = align_signal(context, anchor, config)
    assert result.sweep and result.confirmation is None and "no_post_sweep_confirmation" in result.reasons


def test_future_confirmation_and_stale_context_are_unavailable():
    context, anchor, config = fixture()
    future = replace(context, series=((*context.series[:-1], ("M1", (*context.bars("M1"), Candle(context.decision_time, 1.1, 1.2, 1, 1.15))))))
    assert "confirmation_not_closed" in align_signal(future, anchor, config).reasons
    stale = replace(context, series=(("M5", context.bars("M5")), ("M1", context.bars("M1")[:-4])))
    assert "confirmation_context_stale" in align_signal(stale, anchor, config).reasons


def test_future_provenance_cannot_be_joined_to_an_earlier_decision():
    context, anchor, config = fixture()
    result = evaluate(context, config, pip=.0001, tick_size=.00001, entry_price=1.10045,
                      candidate_side="BUY", anchor=anchor, signal_context=replace(context, decision_time=context.decision_time+60))
    assert result.proposal is None and "anchor_context_mismatch" in result.reasons


def test_snapshot_keeps_forming_m1_out_and_never_reduces_warmup():
    from dataclasses import asdict
    context, anchor, config = fixture()
    rates = {tf: [asdict(row) for row in rows] for tf, rows in context.series}
    rates["M1"].append(dict(time=context.decision_time, open=1, high=100, low=.1, close=99))
    result = snapshot("EURUSD", context.decision_time, rates, config, additional_timeframes=("M1",))
    assert result.bars("M1")[-1].time == context.decision_time-60
    with pytest.raises(ValueError, match="cannot reduce"):
        snapshot("EURUSD", context.decision_time, rates, config, lookbacks={"M5": 1})


def test_real_policy_alignment_still_uses_final_risk_sizing_and_spread_guard(tmp_path, monkeypatch):
    from dataclasses import asdict
    from src.backtesting.adaptive import AdaptiveReplayPolicy
    from src.backtesting.costs import ExecutionCosts
    from src.backtesting.history import HistoricalData
    from src.risk.sizing import SymbolTradeInfo
    from src.services.config import load_config
    from src.strategy.adaptive import engine
    from src.tools.backtest_mt5 import PendingSetupLite, _build_entry_trade

    context, anchor, config = fixture()
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)
    rates = {tf: [asdict(row) for row in rows] for tf, rows in context.series}
    for tf, step in (("H1", 3600), ("H4", 14400)):
        rates[tf] = [asdict(Candle(context.decision_time+(i-100)*step, 1.1, 1.101, 1.099, 1.1)) for i in range(100)]
    history = HistoricalData("EURUSD", info, rates)
    app = load_config(tmp_path/"defaults.json")
    cfg = app.symbols[0]
    pending = PendingSetupLite("BUY|1.09900", "BUY", anchor.level, anchor.candle_time, anchor.expires_at)
    monkeypatch.setattr(engine, "detect_regime", lambda *_: RegimeResult(Regime.RANGING, .0005, 10, .5, .001, 0, "controlled_regime"))
    monkeypatch.setattr(engine, "directions", lambda *_: (("H1", "BUY"), ("H4", "BUY")))
    costs = ExecutionCosts("fixed", 1, 3.5, .2)

    def build(equity=10000, spread=1):
        policy = AdaptiveReplayPolicy(history, config, "adaptive")
        trade = _build_entry_trade(cfg, app.runtime, info, equity, "BUY", context.decision_time,
                                   1.10045, pending.signal_key, "confirmed", pending, costs=costs,
                                   spread_pips=spread, entry_policy=policy.entry)
        return trade, policy

    trade, policy = build()
    assert trade is not None and trade.risk_money <= 10000*cfg.risk_pct/100
    assert trade.sl < 1.0984 and trade.tp == pytest.approx(1.106)
    assert policy.observations[0]["anchor"]["confirmation_timeframe"] == "M1"
    assert next(item for item in policy.observations[0]["evaluation"]["score"]["observations"] if item["name"] == "structure")["value"] == 1
    assert build(equity=1)[0] is None  # An unaffordable broker minimum never becomes an order.
    assert build(spread=20)[0] is None
