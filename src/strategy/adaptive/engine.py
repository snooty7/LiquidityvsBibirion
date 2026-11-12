"""Broker-independent deterministic proposals; no order submission path."""
import hashlib
import math

from src.backtesting.history import TIMEFRAMES
from src.strategy.adaptive.config import AdaptiveConfig
from src.strategy.adaptive.context import directions
from src.strategy.adaptive.models import (
    EntryProposal, Evaluation, FeatureObservation, MarketSnapshot, Regime, VERSION,
)
from src.strategy.adaptive.regime import detect_regime
from src.strategy.adaptive.scoring import score_features
from src.strategy.adaptive.structure import analyze_structure


def evaluate(context: MarketSnapshot, config: AdaptiveConfig, *, pip: float,
             tick_size: float, entry_price: float, candidate_side: str | None = None,
             order_flow: FeatureObservation | None = None, seen_keys: frozenset[str] = frozenset()) -> Evaluation:
    """Create a structure/ATR stop and existing-liquidity target, subject to gates.

    Risk sizing is deliberately separate and authoritative. Callers must not send
    this proposal without the existing guard chain and adaptive preflight.
    """
    bars = context.bars(config.entry_timeframe)
    regime = detect_regime(bars, config)
    structure = analyze_structure(bars, config, regime.atr, pip) if pip > 0 else analyze_structure((), config, 0, 1)
    alignment = directions(context, config)
    reasons = list(context.reasons)
    if not config.enabled:
        reasons.append("adaptive_disabled")
    if not all(math.isfinite(value) and value > 0 for value in (pip, tick_size, entry_price)):
        reasons.append("invalid_entry_metadata")
    if regime.regime in {Regime.UNCERTAIN, Regime.HIGH_VOLATILITY}:
        reasons.append(f"regime_block:{regime.regime.value}")
    step = TIMEFRAMES[config.entry_timeframe]
    sweeps = [event for event in structure.events if event.kind == "SWEEP"
              and context.decision_time-event.available_at <= config.sweep_expiry_bars*step]
    side = candidate_side or (sweeps[-1].side if sweeps else None)
    if side not in {"BUY", "SELL"}:
        reasons.append("no_sweep")
    sweep = next((event for event in reversed(sweeps) if event.side == side), None)
    breaks = [event for event in structure.events if event.kind in {"BOS", "MSS"} and event.side == side
              and sweep is not None and event.available_at > sweep.available_at]
    broken = breaks[-1] if breaks else None
    if sweep is None:
        reasons.append("no_matching_sweep")
    if broken is None:
        reasons.append("no_post_sweep_structure")
    if any(direction != side for _, direction in alignment):
        reasons.append("timeframe_conflict")
    if regime.regime == Regime.TRENDING_BULLISH and side != "BUY" or regime.regime == Regime.TRENDING_BEARISH and side != "SELL":
        reasons.append("regime_direction_conflict")
    active = [zone for zone in structure.zones if zone.side == side and zone.status == "active"]
    zone_quality = max((max(0.0, 1-abs(entry_price-(zone.low+zone.high)/2)/max(regime.atr*2, 1e-12)) for zone in active), default=0.0)
    observations = (
        FeatureObservation("sweep", min(1.0, sweep.strength) if sweep else None, "penetration_atr", context.decision_time,
                           (("penetration_atr", sweep.strength),) if sweep else ()),
        FeatureObservation("structure", min(1.0, broken.strength) if broken else None, "break_strength_atr", context.decision_time,
                           (("break_strength_atr", broken.strength),) if broken else ()),
        FeatureObservation("zone", zone_quality if active else None, "max_fvg_ob_proximity" if active else "no_active_zone", context.decision_time,
                           (("active_zone_count", float(len(active))),)),
        FeatureObservation("regime", 1.0 if regime.regime not in {Regime.UNCERTAIN, Regime.HIGH_VOLATILITY} else 0.0, regime.reason, context.decision_time,
                           (("atr", regime.atr), ("adx", regime.adx), ("atr_percentile", regime.atr_percentile), ("realized_volatility", regime.realized_volatility))),
        order_flow or FeatureObservation("order_flow", None, "exchange_flow_unavailable_tick_volume_not_substituted", context.decision_time),
    )
    if order_flow is not None and order_flow.name != "order_flow":
        raise ValueError("Order flow observation must be named order_flow")
    score = score_features(observations, config, context.decision_time)
    reasons.extend(score.reasons)
    proposal = None
    if not reasons and sweep and side:
        sweep_index = next(index for index, bar in enumerate(bars) if bar.time+step == sweep.available_at)
        extreme = min(bar.low for bar in bars[sweep_index:]) if side == "BUY" else max(bar.high for bar in bars[sweep_index:])
        raw_stop = extreme-regime.atr*config.stop_atr_buffer if side == "BUY" else extreme+regime.atr*config.stop_atr_buffer
        sl = (math.floor(raw_stop/tick_size) if side == "BUY" else math.ceil(raw_stop/tick_size))*tick_size
        targets = [level for level in structure.liquidity if (level-entry_price if side == "BUY" else entry_price-level) > 0]
        target = min(targets, key=lambda level: abs(level-entry_price)) if targets else None
        if target is None:
            reasons.append("liquidity_target_unavailable")
        else:
            tp = round(target/tick_size)*tick_size
            risk_distance = entry_price-sl if side == "BUY" else sl-entry_price
            reward = tp-entry_price if side == "BUY" else entry_price-tp
            if sl <= 0 or risk_distance <= 0 or reward < config.min_rr*risk_distance:
                reasons.append("invalid_stop_or_reward_risk")
            else:
                key = hashlib.sha256(f"{VERSION}:{context.symbol}:{side}:{sweep.available_at}:{broken.available_at}:{config.digest()}".encode()).hexdigest()
                if key in seen_keys:
                    reasons.append("duplicate_signal")
                else:
                    proposal = EntryProposal(key, context.symbol, side, context.decision_time, entry_price, sl, tp,
                                             score, regime, alignment, structure, config.digest(), context.source_digest)
    return Evaluation(proposal, tuple(dict.fromkeys(reasons)), regime, score, alignment, structure)
