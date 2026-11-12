"""Pure one-way exit decisions; initial R never changes as a stop tightens."""
from dataclasses import dataclass
import math

from src.risk.preflight import partial_close_volume
from src.risk.sizing import SymbolTradeInfo
from src.strategy.adaptive.config import AdaptiveConfig


@dataclass(frozen=True)
class ExitDecision:
    stop: float | None = None
    close_volume: float = 0.0
    milestone: str | None = None
    reason: str = "hold"


def decide_exit(*, side: str, entry: float, initial_stop: float, current_stop: float,
                exit_price: float, volume: float, info: SymbolTradeInfo,
                config: AdaptiveConfig, completed: frozenset[str] = frozenset()) -> ExitDecision:
    """Return only tighter tick-aligned protection and a valid one-shot partial.

    The caller persists a milestone only after a reconciled fill; an offline
    simulator updates it atomically. This function cannot place a close order.
    """
    if side not in {"BUY", "SELL"} or not all(math.isfinite(v) and v > 0 for v in (entry, initial_stop, current_stop, exit_price, volume, info.trade_tick_size)):
        return ExitDecision(reason="invalid_exit_context")
    distance = entry-initial_stop if side == "BUY" else initial_stop-entry
    if distance <= 0:
        return ExitDecision(reason="invalid_initial_risk")
    favorable = exit_price-entry if side == "BUY" else entry-exit_price
    current_r = favorable/distance
    candidates = []
    if config.break_even_r > 0 and current_r >= config.break_even_r:
        candidates.append(entry)
    if config.trailing_activation_r > 0 and current_r >= config.trailing_activation_r:
        candidates.append(exit_price-distance*config.trailing_gap_r if side == "BUY" else exit_price+distance*config.trailing_gap_r)
    stop = None
    if candidates:
        raw = max(candidates) if side == "BUY" else min(candidates)
        tick = info.trade_tick_size
        desired = (math.floor(raw/tick) if side == "BUY" else math.ceil(raw/tick))*tick
        if (current_stop < desired < exit_price if side == "BUY" else exit_price < desired < current_stop):
            stop = desired
    close = 0.0
    if config.partial_exit_r > 0 and current_r >= config.partial_exit_r and "partial_1" not in completed:
        close = partial_close_volume(volume, config.partial_exit_fraction, info)
    return ExitDecision(stop, close, "partial_1" if close else None, "tighten_or_partial" if stop or close else "hold")
