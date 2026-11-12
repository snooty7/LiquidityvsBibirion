"""Normalization contracts, without historical score/trade-count targets."""
from dataclasses import replace
from itertools import permutations
import math

import pytest

from src.strategy.adaptive.config import AdaptiveConfig
from src.strategy.adaptive.indicators import closed_atr_series
from src.strategy.adaptive.models import Candle, FeatureObservation, Regime, RegimeResult, StructureEvent, Zone
from src.strategy.adaptive.normalization import event_observation, regime_observation, zone_observation
from src.strategy.adaptive.regime import detect_regime
from src.strategy.adaptive.scoring import COMPONENTS, score_features
from src.strategy.filters import order_block_distance_pips


@pytest.mark.parametrize("side", ["BUY", "SELL"])
@pytest.mark.parametrize("price", [90.0, 100.0, 109.0, 110.0])
def test_inside_wide_zone_is_zero_interval_distance(side, price):
    zone = Zone("FVG", side, 90, 110, 100, "active")
    result = zone_observation((zone,), side, price, 1, 100)
    assert order_block_distance_pips(price, 90, 110, 1) == 0
    assert result.value == 1 and dict(result.raw)["distance_price"] == 0
    if price in {90, 109, 110}:
        old_midpoint_value = max(0, 1-abs(price-100)/2)
        assert old_midpoint_value == 0  # reproduces a false zero-proximity observation


def test_zone_clipping_scaling_translation_and_max_aggregation():
    first = Zone("FVG", "BUY", 10, 11, 100, "active")
    result = zone_observation((first,), "BUY", 12, 1, 100)
    assert result.value == .5
    assert zone_observation((replace(first, low=100, high=110),), "BUY", 120, 10, 100).value == result.value
    assert zone_observation((replace(first, low=60, high=61),), "BUY", 62, 1, 100).value == result.value
    second = Zone("OB", "BUY", 11, 12, 100, "active")
    assert zone_observation((first, second), "BUY", 12, 1, 100).value == 1
    assert zone_observation((second, second), "BUY", 12, 1, 100).value == 1
    assert zone_observation((first,), "BUY", 20, 1, 100).value == 0


@pytest.mark.parametrize("zone", [Zone("FVG", "BUY", 12, 10, 100, "active"),
                                  Zone("FVG", "BUY", 10, float("nan"), 100, "active"),
                                  Zone("FVG", "BUY", 10, 11, 101, "active")])
def test_invalid_or_future_zone_is_unavailable(zone):
    result = zone_observation((zone,), "BUY", 12, 1, 100)
    assert result.value is None


def test_wrong_side_mitigated_and_missing_atr_do_not_confirm_zone():
    zone = Zone("OB", "SELL", 10, 11, 100, "active")
    assert zone_observation((zone,), "BUY", 10, 1, 100).value is None
    assert zone_observation((replace(zone, status="mitigated"),), "SELL", 10, 1, 100).value is None
    assert zone_observation((zone,), "SELL", 10, 0, 100).value is None


@pytest.mark.parametrize("strength,expected", [(0, 0), (.1, .1), (.5, .5), (1, 1), (2, 1)])
def test_event_strength_is_monotone_bounded_and_auditable(strength, expected):
    event = StructureEvent("SWEEP", "BUY", 10, 0, 100, strength, "M5",
                           raw_move=strength*2, normalization_atr=2)
    result = event_observation("sweep", event, 100)
    assert result.value == expected
    raw = dict(result.raw)
    assert raw["move_atr"] == raw["move_price"]/raw["atr"]
    assert event_observation("sweep", replace(event, raw_move=strength*20, normalization_atr=20), 100).value == result.value


@pytest.mark.parametrize("strength", [float("nan"), float("inf"), -1])
def test_invalid_event_cannot_be_clipped_into_valid_confirmation(strength):
    event = StructureEvent("SWEEP", "BUY", 10, 0, 100, strength)
    result = event_observation("sweep", event, 100)
    assert result.value is None
    score = score_features((result,), AdaptiveConfig(), 100)
    assert "required_feature_unavailable:sweep" in score.reasons


def test_raw_ratio_inconsistency_and_future_events_are_unavailable():
    event = StructureEvent("BOS", "BUY", 10, 0, 100, 1, raw_move=1, normalization_atr=0)
    assert event_observation("structure", event, 100).value is None
    assert event_observation("structure", replace(event, normalization_atr=2), 100).value is None
    assert event_observation("structure", replace(event, available_at=101), 100).value is None


@pytest.mark.parametrize("state,side,value", [
    (Regime.TRENDING_BULLISH, "BUY", 1), (Regime.TRENDING_BULLISH, "SELL", 0),
    (Regime.TRENDING_BEARISH, "SELL", 1), (Regime.TRENDING_BEARISH, "BUY", 0),
    (Regime.RANGING, "BUY", 1), (Regime.RANGING, "SELL", 1),
    (Regime.HIGH_VOLATILITY, "BUY", 0), (Regime.UNCERTAIN, "SELL", 0),
])
def test_regime_bonus_means_side_compatibility(state, side, value):
    regime = RegimeResult(state, .1, 20, .5, .001, 1, "controlled")
    assert regime_observation(regime, side, 100).value == value
    assert regime_observation(replace(regime, reason="insufficient_context"), side, 100).value is None


def test_aggregation_keeps_fixed_denominator_names_availability_and_boundary():
    config = AdaptiveConfig()
    items = tuple(FeatureObservation(name, value, "controlled", 100) for name, value in
                  zip(COMPONENTS, (1, 1, .5, 0, None)))
    result = score_features(items, config, 100)
    assert result.score == pytest.approx(.65) and not result.reasons
    assert dict(result.contributions)["order_flow"] == 0
    assert all(score_features(tuple(order), config, 100) == result for order in permutations(items))
    below = tuple(replace(item, value=.5-1e-6) if item.name == "zone" else item for item in items)
    assert "score_below_threshold" in score_features(below, config, 100).reasons
    assert "required_feature_unavailable:order_flow" in score_features(items, replace(config, require_order_flow=True), 100).reasons
    maximum = tuple(replace(item, value=1) if item.name != "order_flow" else item for item in items)
    assert score_features(maximum, config, 100).score == pytest.approx(.9)
    missing_regime = tuple(replace(item, value=None) if item.name == "regime" else item for item in items)
    assert "required_feature_unavailable:regime" in score_features(missing_regime, config, 100).reasons


def test_shared_atr_uses_real_transitions_and_matches_regime_normalization():
    rows = tuple(Candle(i*300, 1.1-i*.0002, 1.1002-i*.0002, 1.0998-i*.0002, 1.10005-i*.0002) for i in range(100))
    series = closed_atr_series(rows, 14)
    assert len(series) == 86 and all(math.isclose(value, .00045, rel_tol=1e-10) for value in series)
    assert detect_regime(rows, AdaptiveConfig()).atr == series[-1]
