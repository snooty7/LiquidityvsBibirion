from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover
    mt5 = None


class MT5UnavailableError(RuntimeError):
    pass


TIMEFRAME_MAP = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
}


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    retcode: Optional[int]
    order: Optional[int]
    deal: Optional[int]
    price: float
    sl: float
    tp: float
    raw: Optional[object]


@dataclass(frozen=True)
class CloseResult:
    ok: bool
    retcode: Optional[int]
    order: Optional[int]
    deal: Optional[int]
    price: float
    raw: Optional[object]


class MT5Adapter:
    def __init__(self, default_deviation: int = 20) -> None:
        self.default_deviation = int(default_deviation)

    def _ensure_mt5(self) -> None:
        if mt5 is None:
            raise MT5UnavailableError("MetaTrader5 package is not installed.")

    def initialize(self) -> None:
        self._ensure_mt5()
        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")

    def shutdown(self) -> None:
        if mt5 is not None:
            mt5.shutdown()

    def timeframe_from_label(self, label: str) -> int:
        self._ensure_mt5()
        normalized = label.upper()
        attr = TIMEFRAME_MAP.get(normalized)
        if attr is None:
            raise ValueError(f"Unsupported timeframe: {label}")
        return int(getattr(mt5, attr))

    def symbol_info(self, symbol: str):
        self._ensure_mt5()
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"Unknown symbol: {symbol}")
        return info

    def ensure_symbol(self, symbol: str) -> None:
        info = self.symbol_info(symbol)
        if not info.visible and not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"symbol_select failed for {symbol}: {mt5.last_error()}")

    def copy_rates(self, symbol: str, timeframe_label: str, bars: int):
        self._ensure_mt5()
        timeframe = self.timeframe_from_label(timeframe_label)
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
        if rates is None:
            raise RuntimeError(f"copy_rates_from_pos failed for {symbol}/{timeframe_label}: {mt5.last_error()}")
        return rates

    def symbol_tick(self, symbol: str):
        self._ensure_mt5()
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"No tick for {symbol}")
        return tick

    def account_equity(self) -> float:
        self._ensure_mt5()
        account = mt5.account_info()
        if account is None:
            raise RuntimeError("No account info. Is MT5 logged in?")
        return float(account.equity)

    @staticmethod
    def pip_size(symbol_info: object) -> float:
        digits = int(symbol_info.digits)
        point = float(symbol_info.point)
        if digits in (3, 5):
            return 10.0 * point
        return point

    def spread_pips(self, symbol: str, symbol_info: Optional[object] = None) -> float:
        info = symbol_info or self.symbol_info(symbol)
        tick = self.symbol_tick(symbol)
        pip = self.pip_size(info)
        return float((tick.ask - tick.bid) / pip)

    def positions_get(self, symbol: str, magic: Optional[int] = None) -> list[object]:
        self._ensure_mt5()
        positions = mt5.positions_get(symbol=symbol)
        if positions is None:
            return []
        if magic is None:
            return list(positions)
        return [p for p in positions if int(getattr(p, "magic", -1)) == int(magic)]

    def quote_market_order(self, symbol: str, side: Literal["BUY", "SELL"], sl_pips: float, tp_pips: float) -> tuple[float, float, float]:
        info = self.symbol_info(symbol)
        tick = self.symbol_tick(symbol)
        pip = self.pip_size(info)

        if side == "BUY":
            price = float(tick.ask)
            sl = price - sl_pips * pip
            tp = price + tp_pips * pip
        else:
            price = float(tick.bid)
            sl = price + sl_pips * pip
            tp = price - tp_pips * pip

        return price, sl, tp

    def _fill_modes(self) -> list[int]:
        modes = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, getattr(mt5, "ORDER_FILLING_RETURN", 2)]
        return list(dict.fromkeys(modes))

    def send_market_order_with_fallback(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        volume: float,
        sl_pips: float,
        tp_pips: float,
        magic: int,
        comment: str,
        deviation: Optional[int] = None,
    ) -> ExecutionResult:
        self._ensure_mt5()

        info = self.symbol_info(symbol)
        tick = self.symbol_tick(symbol)
        pip = self.pip_size(info)
        deviation = self.default_deviation if deviation is None else int(deviation)

        if side == "BUY":
            price = float(tick.ask)
            sl = price - sl_pips * pip
            tp = price + tp_pips * pip
            order_type = mt5.ORDER_TYPE_BUY
        else:
            price = float(tick.bid)
            sl = price + sl_pips * pip
            tp = price - tp_pips * pip
            order_type = mt5.ORDER_TYPE_SELL

        invalid_fill_retcode = int(getattr(mt5, "TRADE_RETCODE_INVALID_FILL", 10030))

        last_result = None
        for fill_type in self._fill_modes():
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(volume),
                "type": order_type,
                "price": float(price),
                "sl": float(sl),
                "tp": float(tp),
                "deviation": deviation,
                "magic": int(magic),
                "comment": str(comment)[:31],
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": fill_type,
            }
            result = mt5.order_send(request)
            last_result = result

            if result is None:
                break

            retcode = getattr(result, "retcode", None)
            if retcode != invalid_fill_retcode:
                break

        retcode = getattr(last_result, "retcode", None) if last_result is not None else None
        is_done = retcode == mt5.TRADE_RETCODE_DONE

        return ExecutionResult(
            ok=bool(is_done),
            retcode=retcode,
            order=getattr(last_result, "order", None) if last_result is not None else None,
            deal=getattr(last_result, "deal", None) if last_result is not None else None,
            price=float(price),
            sl=float(sl),
            tp=float(tp),
            raw=last_result,
        )

    def close_position_market_with_fallback(
        self,
        symbol: str,
        position: object,
        magic: int,
        reason: str,
        deviation: Optional[int] = None,
    ) -> CloseResult:
        self._ensure_mt5()

        tick = self.symbol_tick(symbol)
        deviation = self.default_deviation if deviation is None else int(deviation)

        close_side = mt5.ORDER_TYPE_SELL if int(position.type) == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        close_price = float(tick.bid if close_side == mt5.ORDER_TYPE_SELL else tick.ask)
        invalid_fill_retcode = int(getattr(mt5, "TRADE_RETCODE_INVALID_FILL", 10030))

        last_result = None
        for fill_type in self._fill_modes():
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(position.volume),
                "type": close_side,
                "position": int(position.ticket),
                "price": close_price,
                "deviation": deviation,
                "magic": int(magic),
                "comment": f"CLOSE:{reason}"[:31],
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": fill_type,
            }
            result = mt5.order_send(request)
            last_result = result

            if result is None:
                break

            retcode = getattr(result, "retcode", None)
            if retcode != invalid_fill_retcode:
                break

        retcode = getattr(last_result, "retcode", None) if last_result is not None else None
        is_done = retcode == mt5.TRADE_RETCODE_DONE

        return CloseResult(
            ok=bool(is_done),
            retcode=retcode,
            order=getattr(last_result, "order", None) if last_result is not None else None,
            deal=getattr(last_result, "deal", None) if last_result is not None else None,
            price=close_price,
            raw=last_result,
        )

    def realized_pnl_today(self, magics: set[int], now_utc: datetime) -> float:
        self._ensure_mt5()
        day_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        deals = mt5.history_deals_get(day_start, now_utc)
        if deals is None:
            return 0.0

        deal_entry_out = getattr(mt5, "DEAL_ENTRY_OUT", 1)
        deal_entry_out_by = getattr(mt5, "DEAL_ENTRY_OUT_BY", 3)
        total = 0.0

        for deal in deals:
            if int(getattr(deal, "magic", -1)) not in magics:
                continue
            if getattr(deal, "entry", None) not in (deal_entry_out, deal_entry_out_by):
                continue

            profit = float(getattr(deal, "profit", 0.0) or 0.0)
            commission = float(getattr(deal, "commission", 0.0) or 0.0)
            swap = float(getattr(deal, "swap", 0.0) or 0.0)
            fee = float(getattr(deal, "fee", 0.0) or 0.0)
            total += profit + commission + swap + fee

        return float(total)