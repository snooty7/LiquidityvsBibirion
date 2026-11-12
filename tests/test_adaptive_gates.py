"""Gate contracts use controlled candles, never historical trade-count targets."""
from dataclasses import asdict, replace
from itertools import product
import json
import math
from statistics import pstdev

import pytest

from src.strategy.adaptive.config import AdaptiveConfig
from src.strategy.adaptive.context import directions, snapshot, timeframe_block_reasons
from src.strategy.adaptive.models import Candle, MarketSnapshot, Regime
from src.strategy.adaptive.regime import detect_regime
from src.strategy.filters import evaluate_bias
from src.strategy.liquidity import _atr_series


def candles(count=100, step=300, offset=0, trend=-.0002):
    return tuple(Candle(offset+i*step, 1.1+i*trend, 1.1002+i*trend,
                        1.0998+i*trend, 1.10005+i*trend) for i in range(count))


def test_unknown_first_transition_cannot_manufacture_an_atr_extreme():
    config = AdaptiveConfig()
    rows = candles()
    known_ranges = [max(b.high-b.low, abs(b.high-a.close), abs(b.low-a.close)) for a, b in zip(rows, rows[1:])]
    assert all(value == pytest.approx(.00045) for value in known_ranges)
    old = _atr_series(rows, config.atr_period)
    old_rank = sum(value < old[-1] and not math.isclose(value, old[-1], rel_tol=1e-6)
                   for value in old[config.atr_period:-1])/len(old[config.atr_period:-1])
    assert old_rank >= config.high_atr_percentile  # controlled reproduction of the defect
    result = detect_regime(rows, config)
    assert result.atr == pytest.approx(.00045)
    assert result.atr_percentile == 0 and result.regime == Regime.TRENDING_BEARISH


def test_regime_fixed_window_ignores_extra_older_inputs():
    config = AdaptiveConfig()
    used = candles()
    prefix = (Candle(-300, float("nan"), 5, 1, 2),)
    assert detect_regime(prefix+used, config) == detect_regime(used, config)


def test_real_atr_spike_remains_blocked_at_the_unchanged_cutoff():
    config = AdaptiveConfig()
    rows = list(candles(trend=0))
    rows[-1] = replace(rows[-1], high=1.12, low=1.08)
    result = detect_regime(tuple(rows), config)
    assert config.high_atr_percentile == .98
    assert result.atr_percentile == 1 and result.realized_volatility < config.high_realized_volatility
    assert result.regime == Regime.HIGH_VOLATILITY


def test_realized_volatility_is_unannualized_and_its_boundary_is_inclusive():
    config = AdaptiveConfig()
    rows = tuple(Candle(i*300, 1.1, 1.2, 1, 1.11 if i % 2 else 1.09) for i in range(100))
    returns = [math.log(b.close/a.close) for a, b in zip(rows[-21:-1], rows[-20:])]
    measured = pstdev(returns)
    result = detect_regime(rows, config)
    assert result.atr_percentile == 0
    assert result.realized_volatility == measured and measured > .01
    assert result.regime == Regime.HIGH_VOLATILITY
    assert detect_regime(rows, replace(config, high_realized_volatility=measured)).regime == Regime.HIGH_VOLATILITY
    assert detect_regime(rows, replace(config, high_realized_volatility=math.nextafter(measured, math.inf))).regime != Regime.HIGH_VOLATILITY


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0])
def test_used_invalid_prices_fail_closed_without_nan_outputs(value):
    rows = list(candles())
    rows[-1] = replace(rows[-1], close=value)
    result = detect_regime(tuple(rows), AdaptiveConfig())
    assert result.regime == Regime.UNCERTAIN and result.reason == "invalid_context"
    json.dumps(asdict(result), allow_nan=False)


def test_old_provenance_prefix_cannot_flip_fixed_window_direction():
    config = AdaptiveConfig(context_timeframes=("H1",))
    used = candles(step=3600, trend=.00000001)
    prefix = tuple(Candle((i-100)*3600, 2, 2.001, 1.999, 2) for i in range(100))
    long = MarketSnapshot("EURUSD", 100*3600, (("H1", prefix+used),), "controlled")
    fixed = replace(long, series=(("H1", used),))
    assert evaluate_bias(prefix+used, 20)["ok_sell"]  # reproduces the untrimmed input bug
    assert directions(long, config) == directions(fixed, config) == (("H1", "BUY"),)
    short = replace(long, series=(("H1", used[-99:]),))
    assert directions(short, config) == (("H1", "UNCERTAIN"),)


@pytest.mark.parametrize("side,states", [(side, states) for side in ("BUY", "SELL")
                                        for states in product(("BUY", "SELL", "UNCERTAIN"), repeat=2)])
def test_unanimous_direction_requirement_is_not_weakened(side, states):
    alignment = tuple(zip(("H1", "H4"), states))
    reasons = timeframe_block_reasons(alignment, side, ("H1", "H4"))
    assert bool(reasons) == any(state != side for state in states)
    assert ("timeframe_conflict" in reasons) == any(state in {"BUY", "SELL"} and state != side for state in states)
    for tf, state in alignment:
        if state == "UNCERTAIN":
            assert f"timeframe_uncertain:{tf}" in reasons


def test_missing_or_duplicate_timeframes_are_not_silent_agreement():
    assert timeframe_block_reasons((("H1", "BUY"),), "BUY", ("H1", "H4")) == ("timeframe_context_invalid",)
    assert timeframe_block_reasons((("H1", "BUY"), ("H1", "BUY")), "BUY", ("H1", "H4")) == ("timeframe_context_invalid",)


def test_exact_htf_close_boundary_excludes_future_direction_changes():
    config = AdaptiveConfig()
    end = 1_440_000
    rates = {}
    for tf, step, count in (("M5", 300, 500), ("H1", 3600, 420), ("H4", 14400, 101)):
        rates[tf] = [dict(time=end+(i-count)*step, open=1.1+i*.00001, high=1.101+i*.00001,
                          low=1.099+i*.00001, close=1.1+i*.00001) for i in range(count)]
    rates["H4"][-1].update(open=1.11, high=1.2, low=.8, close=.9)
    before = snapshot("EURUSD", end-1, rates, config)
    closed = snapshot("EURUSD", end, rates, config)
    assert not before.reasons and not closed.reasons
    assert before.bars("H4")[-1].time+14400 == end-14400
    assert closed.bars("H4")[-1].time+14400 == end
    assert dict(directions(before, config))["H4"] == "BUY"
    assert dict(directions(closed, config))["H4"] == "SELL"
