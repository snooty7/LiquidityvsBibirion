"""Immutable observations and proposals, with no execution capabilities."""
from dataclasses import dataclass
from enum import Enum

VERSION = "adaptive-v1-research"


class Regime(str, Enum):
    TRENDING_BULLISH = "TRENDING_BULLISH"
    TRENDING_BEARISH = "TRENDING_BEARISH"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class Candle:
    time: int
    open: float
    high: float
    low: float
    close: float
    tick_volume: float = 0.0

    def __getitem__(self, name: str):
        return getattr(self, name)


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    decision_time: int
    series: tuple[tuple[str, tuple[Candle, ...]], ...]
    source_digest: str
    reasons: tuple[str, ...] = ()

    def bars(self, timeframe: str) -> tuple[Candle, ...]:
        """Return immutable closed context, or an empty unavailable series."""
        return dict(self.series).get(timeframe, ())


@dataclass(frozen=True)
class FeatureObservation:
    name: str
    value: float | None
    reason: str
    observed_at: int
    raw: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class RegimeResult:
    regime: Regime
    atr: float
    adx: float
    atr_percentile: float
    realized_volatility: float
    momentum_atr: float
    reason: str


@dataclass(frozen=True)
class StructureEvent:
    kind: str
    side: str
    price: float
    pivot_time: int
    available_at: int
    strength: float = 0.0


@dataclass(frozen=True)
class Zone:
    kind: str
    side: str
    low: float
    high: float
    available_at: int
    status: str


@dataclass(frozen=True)
class StructureContext:
    events: tuple[StructureEvent, ...]
    zones: tuple[Zone, ...]
    liquidity: tuple[float, ...]
    dealing_low: float | None
    dealing_high: float | None
    price_zone: str = "UNAVAILABLE"


@dataclass(frozen=True)
class ScoreBreakdown:
    score: float
    contributions: tuple[tuple[str, float], ...]
    observations: tuple[FeatureObservation, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class EntryProposal:
    key: str
    symbol: str
    side: str
    decision_time: int
    entry: float
    sl: float
    tp: float
    score: ScoreBreakdown
    regime: RegimeResult
    directions: tuple[tuple[str, str], ...]
    structure: StructureContext
    config_digest: str
    source_digest: str
    version: str = VERSION


@dataclass(frozen=True)
class Evaluation:
    proposal: EntryProposal | None
    reasons: tuple[str, ...]
    regime: RegimeResult
    score: ScoreBreakdown
    directions: tuple[tuple[str, str], ...]
    structure: StructureContext


@dataclass(frozen=True)
class ShadowPrediction:
    probability: float | None
    status: str
    model_digest: str | None = None
