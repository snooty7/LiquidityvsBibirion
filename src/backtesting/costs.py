"""Deterministic execution assumptions for bid-based OHLC history."""
from dataclasses import dataclass
import math

from src.risk.sizing import SymbolTradeInfo, pip_size


@dataclass(frozen=True)
class ExecutionCosts:
    """Commission is in account currency per lot per side; spreads/slippage are pips."""

    spread_mode: str = "historical"
    spread_pips: float = 1.0
    commission_per_lot: float = 3.5
    slippage_pips: float = 0.2

    def __post_init__(self) -> None:
        if self.spread_mode not in {"historical", "fixed"}:
            raise ValueError("spread_mode must be historical or fixed")
        if not all(math.isfinite(v) and v >= 0 for v in (
            self.spread_pips, self.commission_per_lot, self.slippage_pips,
        )):
            raise ValueError("Costs must be finite and nonnegative")

    def spread(self, bar: dict, info: SymbolTradeInfo) -> float:
        """Use MT5's historical spread in points; missing values use the declared fallback."""
        if self.spread_mode == "historical" and "spread" in bar:
            points = float(bar["spread"])
            if not math.isfinite(points) or points < 0:
                raise ValueError("Historical spread must be finite and nonnegative")
            return points * info.point / pip_size(info.digits, info.point)
        return self.spread_pips

    def exit_quote(self, side: str, bid: float, spread: float, pip: float) -> float:
        """Longs close on bid; shorts close on ask."""
        return bid + (spread * pip if side == "SELL" else 0.0)
