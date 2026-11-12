"""Optional observational inference; no training dependency or decision feedback."""
import math
from typing import Callable

from src.strategy.adaptive.models import ShadowPrediction


def observe(features: tuple[float, ...], *, predictor: Callable | None = None,
            model_digest: str | None = None) -> ShadowPrediction:
    """Record explicit unavailable/error states; never manufacture a probability."""
    if predictor is None or not model_digest:
        return ShadowPrediction(None, "model_unavailable")
    if not all(math.isfinite(value) for value in features):
        return ShadowPrediction(None, "features_unavailable", model_digest)
    try:
        probability = float(predictor(features))
    except Exception as exc:
        return ShadowPrediction(None, f"prediction_error:{type(exc).__name__}:{exc}", model_digest)
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        return ShadowPrediction(None, "invalid_probability", model_digest)
    return ShadowPrediction(probability, "shadow_only", model_digest)


def chronological_split(rows: list[dict], train_end: int, validation_end: int,
                        test_end: int, embargo_seconds: int) -> dict[str, list[dict]]:
    """Purge labels crossing boundaries; rows contain time and label_available_at."""
    if (any(type(value) is not int for value in (train_end, validation_end, test_end, embargo_seconds))
            or not train_end < validation_end < test_end or embargo_seconds < 0):
        raise ValueError("Invalid chronological split")
    output = {"train": [], "validation": [], "test": []}
    previous = -1
    for row in rows:
        timestamp, available = row["time"], row["label_available_at"]
        if type(timestamp) is not int or type(available) is not int or timestamp <= previous or available < timestamp:
            raise ValueError("Rows must be ordered with causal label availability")
        previous = timestamp
        if available < train_end:
            output["train"].append(row)
        elif timestamp >= train_end+embargo_seconds and available < validation_end:
            output["validation"].append(row)
        elif timestamp >= validation_end+embargo_seconds and available < test_end:
            output["test"].append(row)
    return output
