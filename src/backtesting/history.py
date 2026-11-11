"""Validated, reusable history input for offline evaluation."""
from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

from src.risk.sizing import SymbolTradeInfo, pip_value_per_lot


TIMEFRAMES = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400}


def validate_bars(rows: list[dict], timeframe: str) -> list[dict]:
    """Reject ambiguous timestamps and corrupt prices rather than silently repairing them."""
    result = []
    previous = -1
    step = TIMEFRAMES[timeframe]
    for raw in rows:
        row = dict(raw)
        timestamp = row.get("time")
        if not isinstance(timestamp, int) or timestamp <= previous or timestamp % step:
            raise ValueError(f"{timeframe}: timestamps must be unique, sorted UTC bar-open seconds aligned to the timeframe")
        prices = [float(row[k]) for k in ("open", "high", "low", "close")]
        op, high, low, close = prices
        if not all(math.isfinite(v) and v > 0 for v in prices) or not low <= min(op, close) <= max(op, close) <= high:
            raise ValueError(f"{timeframe}: invalid OHLC at {timestamp}")
        if "spread" in row and (not math.isfinite(float(row["spread"])) or float(row["spread"]) < 0):
            raise ValueError("Invalid historical spread")
        result.append(row)
        previous = timestamp
    return result


def resample_m1(rows: list[dict], timeframe: str) -> list[dict]:
    """Aggregate complete UTC buckets only; incomplete/gapped bars are discarded."""
    step = TIMEFRAMES[timeframe]
    buckets: dict[int, list[dict]] = {}
    for row in rows:
        key = row["time"] // step * step
        buckets.setdefault(key, []).append(row)
    output = []
    for key, group in sorted(buckets.items()):
        if [r["time"] for r in group] != list(range(key, key + step, 60)):
            continue
        bar = dict(time=key, open=group[0]["open"], high=max(r["high"] for r in group),
                   low=min(r["low"] for r in group), close=group[-1]["close"],
                   tick_volume=sum(float(r.get("tick_volume", 0)) for r in group))
        # Spread at the final quote, rather than an average unavailable at entry.
        if "spread" in group[-1]:
            bar["spread"] = group[-1]["spread"]
        output.append(bar)
    return output


@dataclass
class HistoricalData:
    symbol: str
    symbol_info: SymbolTradeInfo
    rates: dict[str, list[dict]]
    source: str = "offline"
    _source_timeframes: tuple[str, ...] = field(init=False, repr=False)
    _time_index: dict[str, list[int]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self._source_timeframes = tuple(sorted(self.rates))

    def bars(self, timeframe: str) -> list[dict]:
        """Return supplied bars or derive complete bars from M1 history."""
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"Unsupported historical timeframe: {timeframe}")
        if timeframe not in self.rates:
            self.rates[timeframe] = resample_m1(self.rates["M1"], timeframe)
        return self.rates[timeframe]

    def digest(self) -> str:
        """Fingerprint the source data, independent of derived timeframe caches."""
        payload = {"symbol": self.symbol, "symbol_info": asdict(self.symbol_info),
                   "rates": {tf: self.rates[tf] for tf in self._source_timeframes}}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()

    def timestamps(self, timeframe: str) -> list[int]:
        """Cache sorted bar-open times for repeated window lookups."""
        if timeframe not in self._time_index:
            self._time_index[timeframe] = [row["time"] for row in self.bars(timeframe)]
        return self._time_index[timeframe]


def load_history(path: Path) -> dict[str, HistoricalData]:
    """Load a bid-OHLC JSON bundle without importing or connecting to MT5."""
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if document.get("quote_basis") != "bid":
        raise ValueError("History must explicitly declare quote_basis=bid")
    data = {}
    for symbol, payload in document["symbols"].items():
        info = SymbolTradeInfo(**payload["symbol_info"])
        if not math.isfinite(pip_value_per_lot(info)) or pip_value_per_lot(info) <= 0:
            raise ValueError(f"{symbol}: valid symbol valuation is required")
        if not all(math.isfinite(v) and v > 0 for v in (info.volume_min, info.volume_max, info.volume_step)) or info.volume_min > info.volume_max:
            raise ValueError(f"{symbol}: invalid volume specifications")
        rates = {tf: validate_bars(rows, tf) for tf, rows in payload["rates"].items()}
        if not rates.get("M1"):
            raise ValueError(f"{symbol}: M1 history is required")
        data[symbol] = HistoricalData(symbol, info, rates, str(path.resolve()))
    if not data:
        raise ValueError("History bundle has no symbols")
    return data


def fetch_mt5_history(configs: list, start: datetime, end: datetime) -> dict[str, HistoricalData]:
    """Explicit read-only history fetch. No orchestrator or order methods are called."""
    from src.execution.mt5_adapter import MT5Adapter
    from src.tools.backtest_mt5 import _fetch_chunked_rates, _max_buffer_days
    from datetime import timedelta

    adapter = MT5Adapter()
    output = {}
    try:
        adapter.initialize()
        for symbol in sorted({cfg.symbol for cfg in configs}):
            relevant = [cfg for cfg in configs if cfg.symbol == symbol]
            fetch_start = start - timedelta(days=max(_max_buffer_days(cfg) for cfg in relevant))
            adapter.ensure_symbol(symbol)
            info = SymbolTradeInfo.from_mt5(adapter.symbol_info(symbol))
            rows = _fetch_chunked_rates(adapter, symbol, "M1", fetch_start, end)
            output[symbol] = HistoricalData(symbol, info, {"M1": validate_bars(rows, "M1")}, "MT5 read-only history")
    finally:
        adapter.shutdown()
    return output


def save_history(data: dict[str, HistoricalData], path: Path) -> None:
    """Save a reusable history snapshot for reproducible offline reruns."""
    document = {"quote_basis": "bid", "symbols": {
        name: {"symbol_info": asdict(value.symbol_info),
               "rates": {tf: value.rates[tf] for tf in value._source_timeframes}}
        for name, value in data.items()
    }}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, allow_nan=False), encoding="utf-8")
