"""Fixed-denominator evidence aggregation; scores are not probabilities."""
import math

from src.strategy.adaptive.config import AdaptiveConfig
from src.strategy.adaptive.models import FeatureObservation, ScoreBreakdown

COMPONENTS = ("sweep", "structure", "zone", "regime", "order_flow")


def score_features(observations: tuple[FeatureObservation, ...], config: AdaptiveConfig,
                   decision_time: int) -> ScoreBreakdown:
    """Require critical observations and expose every unavailable component."""
    if len({item.name for item in observations}) != len(observations) or set(item.name for item in observations) - set(COMPONENTS):
        raise ValueError("Duplicate or unknown scoring component")
    lookup = {item.name: item for item in observations}
    contributions, reasons, complete = [], [], []
    for name, weight in zip(COMPONENTS, config.weights):
        item = lookup.get(name, FeatureObservation(name, None, "unavailable", decision_time))
        if item.observed_at > decision_time:
            raise ValueError("Future observation")
        if item.value is not None and (not math.isfinite(item.value) or not 0 <= item.value <= 1):
            raise ValueError("Feature must be normalized into [0,1]")
        if item.value is None:
            if name in {"sweep", "structure", "regime"} or name == "order_flow" and config.require_order_flow:
                reasons.append(f"required_feature_unavailable:{name}")
        contributions.append((name, weight * (item.value or 0.0)))
        complete.append(item)
    score = sum(value for _, value in contributions)
    if score + 1e-12 < config.score_threshold:
        reasons.append("score_below_threshold")
    return ScoreBreakdown(score, tuple(contributions), tuple(complete), tuple(reasons))
