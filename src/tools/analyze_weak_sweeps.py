from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

from src.execution.mt5_adapter import MT5Adapter
from src.risk.sizing import SymbolTradeInfo, pip_size
from src.services.config import load_config


_FLOAT_PATTERNS = {
    "sweep_range": re.compile(r"sweep_range=([0-9.]+)"),
    "avg_range": re.compile(r"avg_range=([0-9.]+)"),
    "penetration": re.compile(r"penetration=([0-9.]+)"),
    "pen_ratio": re.compile(r"pen_ratio=([0-9.]+)"),
    "range_ratio": re.compile(r"range_ratio=([0-9.]+)"),
    "quality": re.compile(r"quality=([0-9.]+)"),
}


def _extract_float(message: str, key: str) -> float:
    pattern = _FLOAT_PATTERNS[key]
    match = pattern.search(message or "")
    if not match:
        return 0.0
    return float(match.group(1))


def _derive_thresholds(config_path: str, symbol: str, timeframe: str) -> tuple[float, float] | tuple[None, None]:
    app_config = load_config(config_path)
    cfg = next((item for item in app_config.symbols if item.symbol == symbol and item.timeframe == timeframe), None)
    if cfg is None:
        return None, None

    adapter = MT5Adapter(default_deviation=app_config.runtime.default_deviation)
    adapter.initialize()
    try:
        info = SymbolTradeInfo.from_mt5(adapter.symbol_info(symbol))
    finally:
        adapter.shutdown()

    pip = pip_size(info.digits, info.point)
    return float(cfg.sweep_min_penetration_pips * pip), float(cfg.sweep_significance_range_multiple)


def _derive_ratios_from_message(message: str, min_penetration_price: float, min_range_multiple: float) -> tuple[float, float, float]:
    penetration = _extract_float(message, "penetration")
    sweep_range = _extract_float(message, "sweep_range")
    avg_range = _extract_float(message, "avg_range")
    required_penetration = max(min_penetration_price, 1e-10)
    required_range = max(avg_range * min_range_multiple, 1e-10)
    pen_ratio = penetration / required_penetration
    range_ratio = sweep_range / required_range
    return pen_ratio, range_ratio, min(pen_ratio, range_ratio)


def run(path: Path, config_path: str, symbol: str, timeframe: str, tail: int) -> int:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("event") != "SKIP_SWEEP_WEAK":
                continue
            if symbol and row.get("symbol") != symbol:
                continue
            if timeframe and row.get("timeframe") != timeframe:
                continue
            rows.append(row)

    if tail > 0:
        rows = rows[-tail:]

    print(f"Weak sweep rows: {len(rows)}")
    if not rows:
        return 0

    min_penetration_price, min_range_multiple = _derive_thresholds(config_path, symbol, timeframe)

    by_reason = Counter()
    quality_buckets = Counter()
    ratios_by_reason: dict[str, list[float]] = defaultdict(list)

    for row in rows:
        message = str(row.get("message") or "")
        reason = message.split(" ", 1)[0] if message else "unknown"
        by_reason[reason] += 1
        pen_ratio = _extract_float(message, "pen_ratio")
        range_ratio = _extract_float(message, "range_ratio")
        quality = _extract_float(message, "quality")
        if (
            min_penetration_price is not None
            and min_range_multiple is not None
            and pen_ratio == 0.0
            and range_ratio == 0.0
            and quality == 0.0
        ):
            pen_ratio, range_ratio, quality = _derive_ratios_from_message(
                message,
                float(min_penetration_price),
                float(min_range_multiple),
            )
        ratios_by_reason[reason].append(quality)
        if quality < 0.25:
            quality_buckets["very_weak_<0.25"] += 1
        elif quality < 0.50:
            quality_buckets["weak_0.25_0.49"] += 1
        elif quality < 0.75:
            quality_buckets["borderline_0.50_0.74"] += 1
        else:
            quality_buckets["near_threshold_>=0.75"] += 1

    print("")
    print("By reject reason:")
    for reason, count in sorted(by_reason.items()):
        avg_quality = sum(ratios_by_reason[reason]) / max(len(ratios_by_reason[reason]), 1)
        print(f"  {reason}: {count} avg_quality={avg_quality:.2f}")

    print("")
    print("By weakness bucket:")
    for bucket, count in sorted(quality_buckets.items()):
        print(f"  {bucket}: {count}")

    print("")
    print("Recent rows:")
    for row in rows[-10:]:
        message = str(row.get("message") or "")
        reason = message.split(" ", 1)[0] if message else "unknown"
        pen_ratio = _extract_float(message, "pen_ratio")
        range_ratio = _extract_float(message, "range_ratio")
        quality = _extract_float(message, "quality")
        if (
            min_penetration_price is not None
            and min_range_multiple is not None
            and pen_ratio == 0.0
            and range_ratio == 0.0
            and quality == 0.0
        ):
            pen_ratio, range_ratio, quality = _derive_ratios_from_message(
                message,
                float(min_penetration_price),
                float(min_range_multiple),
            )
        print(
            f"  {row.get('ts')} {row.get('symbol')} {row.get('timeframe')} {row.get('side')} "
            f"reason={reason} pen_ratio={pen_ratio:.2f} range_ratio={range_ratio:.2f} quality={quality:.2f}"
        )

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze SKIP_SWEEP_WEAK events and score how weak they were.")
    parser.add_argument("--log", default="bot_events.csv", help="CSV event log path")
    parser.add_argument("--config", default="config/settings.json", help="Bot config path for fallback threshold reconstruction")
    parser.add_argument("--symbol", default="EURUSD", help="Optional symbol filter")
    parser.add_argument("--timeframe", default="M5", help="Optional timeframe filter")
    parser.add_argument("--tail", type=int, default=200, help="Analyze only the last N matching rows")
    args = parser.parse_args()
    return run(Path(args.log), str(args.config), str(args.symbol), str(args.timeframe), int(args.tail))


if __name__ == "__main__":
    raise SystemExit(main())
