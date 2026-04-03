from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

from src.execution.mt5_adapter import MT5Adapter


@dataclass(frozen=True)
class WindowPatternStat:
    pattern: str
    count: int
    win_rate_pct: float
    avg_pips: float


def _to_utc_datetime(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _bar_dict(row: object) -> dict:
    return {
        "time": int(row["time"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "tick_volume": int(row["tick_volume"]) if "tick_volume" in row.dtype.names else 0,
        "spread": int(row["spread"]) if "spread" in row.dtype.names else 0,
    }


def _sign(value: float) -> int:
    return 1 if value > 0 else (-1 if value < 0 else 0)


def _pattern_stats(rows: list[dict], *, point: float) -> list[WindowPatternStat]:
    stats: list[WindowPatternStat] = []

    def summarize(name: str, values: list[float]) -> None:
        if not values:
            stats.append(WindowPatternStat(name, 0, 0.0, 0.0))
            return
        wins = sum(1 for item in values if item > 0)
        stats.append(
            WindowPatternStat(
                name,
                len(values),
                round(wins / len(values) * 100.0, 2),
                round(mean(values), 3),
            )
        )

    two_up: list[float] = []
    two_down: list[float] = []
    three_up: list[float] = []
    three_down: list[float] = []
    breakout_vol: list[float] = []
    breakout_vol_down: list[float] = []

    for i in range(8, len(rows) - 3):
        future_2 = (rows[i + 2]["close"] - rows[i]["close"]) / point
        dirs2 = [_sign(rows[j]["close"] - rows[j]["open"]) for j in (i - 2, i - 1)]
        if dirs2[0] == dirs2[1] == 1:
            two_up.append(future_2)
        if dirs2[0] == dirs2[1] == -1:
            two_down.append(-future_2)

        dirs3 = [_sign(rows[j]["close"] - rows[j]["open"]) for j in (i - 3, i - 2, i - 1)]
        if dirs3[0] == dirs3[1] == dirs3[2] == 1:
            three_up.append(future_2)
        if dirs3[0] == dirs3[1] == dirs3[2] == -1:
            three_down.append(-future_2)

        look = rows[i - 8 : i]
        prev_high = max(item["high"] for item in look)
        prev_low = min(item["low"] for item in look)
        avg_vol = sum(item["tick_volume"] for item in look) / len(look)
        if avg_vol > 0 and rows[i]["tick_volume"] > avg_vol:
            if rows[i]["close"] > prev_high:
                breakout_vol.append(future_2)
            elif rows[i]["close"] < prev_low:
                breakout_vol_down.append(-future_2)

    summarize("two_up_next_2bars", two_up)
    summarize("two_down_next_2bars", two_down)
    summarize("three_up_next_2bars", three_up)
    summarize("three_down_next_2bars", three_down)
    summarize("high_volume_breakout_up_next_2bars", breakout_vol)
    summarize("high_volume_breakout_down_next_2bars", breakout_vol_down)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze short-hold M1 patterns in a custom UTC window.")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--start", required=True, help="UTC ISO timestamp, e.g. 2026-04-02T14:15:00+00:00")
    parser.add_argument("--end", required=True, help="UTC ISO timestamp, e.g. 2026-04-02T15:10:00+00:00")
    parser.add_argument("--csv", default="")
    args = parser.parse_args()

    start_utc = _to_utc_datetime(args.start)
    end_utc = _to_utc_datetime(args.end)
    symbol = str(args.symbol).upper()

    adapter = MT5Adapter()
    adapter.initialize()
    adapter.ensure_symbol(symbol)
    rates = adapter.copy_rates_range(symbol, "M1", start_utc, end_utc + timedelta(minutes=3))
    info = adapter.symbol_info(symbol)
    adapter.shutdown()

    rows = [_bar_dict(item) for item in rates]
    point = MT5Adapter.pip_size(info)
    stats = _pattern_stats(rows, point=point)
    for row in stats:
        print(
            f"{row.pattern}: count={row.count} "
            f"win_rate={row.win_rate_pct:.2f}% avg_pips={row.avg_pips:.3f}"
        )

    csv_path = Path(args.csv) if args.csv else Path("reports") / f"m1_window_patterns_{symbol.lower()}.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(WindowPatternStat.__dataclass_fields__.keys()))
        writer.writeheader()
        for row in stats:
            writer.writerow(asdict(row))
    print(f"Wrote {csv_path}")


if __name__ == "__main__":
    main()
