from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

from src.execution.mt5_adapter import MT5Adapter


Side = Literal["BUY", "SELL"]


@dataclass
class ResearchTrade:
    symbol: str
    side: Side
    sweep_type: str
    entry_time_utc: str
    exit_time_utc: str
    entry_price: float
    exit_price: float
    sl: float
    tp: float
    pnl_pips: float
    pnl_r: float
    reason: str
    zone_type: str


def _to_utc(value: str, *, end_of_day: bool = False) -> datetime:
    raw = value.strip()
    if "T" not in raw:
        raw = f"{raw}T{'23:59:59' if end_of_day else '00:00:00'}"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _bar(row: object) -> dict:
    return {
        "time": int(row["time"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "tick_volume": int(row["tick_volume"]) if "tick_volume" in row.dtype.names else 0,
    }


def _fetch_rates(adapter: MT5Adapter, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[dict]:
    rows: list[dict] = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=21), end)
        rows.extend(_bar(item) for item in adapter.copy_rates_range(symbol, timeframe, cursor, chunk_end))
        cursor = chunk_end
    deduped: list[dict] = []
    seen: set[int] = set()
    for row in sorted(rows, key=lambda item: int(item["time"])):
        if int(row["time"]) in seen:
            continue
        seen.add(int(row["time"]))
        deduped.append(row)
    return deduped


def _body_ratio(bar: dict) -> float:
    rng = max(float(bar["high"]) - float(bar["low"]), 1e-10)
    return abs(float(bar["close"]) - float(bar["open"])) / rng


def _pip(symbol: str) -> float:
    if "JPY" in symbol.upper():
        return 0.01
    return 0.0001


def _previous_day_levels(rows: list[dict], index: int) -> tuple[float, float]:
    day = datetime.fromtimestamp(int(rows[index]["time"]), timezone.utc).date()
    previous_day = day - timedelta(days=1)
    day_rows = [
        row
        for row in rows[:index]
        if datetime.fromtimestamp(int(row["time"]), timezone.utc).date() == previous_day
    ]
    if not day_rows:
        return 0.0, 0.0
    return max(float(row["high"]) for row in day_rows), min(float(row["low"]) for row in day_rows)


def _equal_level(levels: list[float], *, tolerance: float, side: Side) -> float:
    if len(levels) < 2:
        return 0.0
    clusters: list[list[float]] = []
    for level in sorted(levels):
        if not clusters or abs(level - clusters[-1][-1]) > tolerance:
            clusters.append([level])
        else:
            clusters[-1].append(level)
    valid = [cluster for cluster in clusters if len(cluster) >= 2]
    if not valid:
        return 0.0
    prices = [sum(cluster) / len(cluster) for cluster in valid]
    return max(prices) if side == "SELL" else min(prices)


def _detect_sweep(
    rows: list[dict],
    index: int,
    *,
    pip: float,
    equal_lookback: int,
    equal_tolerance_pips: float,
    buffer_pips: float,
) -> Optional[tuple[Side, str, float, float]]:
    bar = rows[index]
    prior = rows[max(0, index - equal_lookback) : index]
    if len(prior) < max(10, equal_lookback // 2):
        return None

    buffer = buffer_pips * pip
    tolerance = equal_tolerance_pips * pip
    pd_high, pd_low = _previous_day_levels(rows, index)
    equal_high = _equal_level([float(row["high"]) for row in prior], tolerance=tolerance, side="SELL")
    equal_low = _equal_level([float(row["low"]) for row in prior], tolerance=tolerance, side="BUY")

    candidates: list[tuple[Side, str, float, float]] = []
    for name, level in (("pd_high", pd_high), ("equal_highs", equal_high)):
        if level > 0 and float(bar["high"]) > level + buffer and float(bar["close"]) < level:
            candidates.append(("SELL", name, level, float(bar["high"])))
    for name, level in (("pd_low", pd_low), ("equal_lows", equal_low)):
        if level > 0 and float(bar["low"]) < level - buffer and float(bar["close"]) > level:
            candidates.append(("BUY", name, level, float(bar["low"])))
    if not candidates:
        return None

    return max(candidates, key=lambda item: abs(item[3] - item[2]) / pip)


def _detect_bos(
    rows: list[dict],
    index: int,
    *,
    side: Side,
    structure_lookback: int,
    impulse_lookback: int,
    impulse_range_multiple: float,
    body_ratio_min: float,
) -> bool:
    prior = rows[max(0, index - structure_lookback) : index]
    impulse_context = rows[max(0, index - impulse_lookback) : index]
    if len(prior) < structure_lookback // 2 or len(impulse_context) < impulse_lookback // 2:
        return False
    avg_range = sum(float(row["high"]) - float(row["low"]) for row in impulse_context) / max(len(impulse_context), 1)
    bar = rows[index]
    range_ok = float(bar["high"]) - float(bar["low"]) >= avg_range * impulse_range_multiple
    body_ok = _body_ratio(bar) >= body_ratio_min
    if not range_ok or not body_ok:
        return False
    if side == "BUY":
        return float(bar["close"]) > max(float(row["high"]) for row in prior)
    return float(bar["close"]) < min(float(row["low"]) for row in prior)


def _find_zone(rows: list[dict], bos_index: int, *, side: Side) -> tuple[str, float, float]:
    if bos_index >= 2:
        first = rows[bos_index - 2]
        third = rows[bos_index]
        if side == "BUY" and float(third["low"]) > float(first["high"]):
            return "fvg", float(first["high"]), float(third["low"])
        if side == "SELL" and float(third["high"]) < float(first["low"]):
            return "fvg", float(third["high"]), float(first["low"])

    for idx in range(bos_index - 1, max(-1, bos_index - 8), -1):
        candle = rows[idx]
        bullish = float(candle["close"]) > float(candle["open"])
        bearish = float(candle["close"]) < float(candle["open"])
        if side == "BUY" and bearish:
            return "order_block", min(float(candle["open"]), float(candle["close"])), max(float(candle["open"]), float(candle["close"]))
        if side == "SELL" and bullish:
            return "order_block", min(float(candle["open"]), float(candle["close"])), max(float(candle["open"]), float(candle["close"]))
    return "", 0.0, 0.0


def _m1_bos_confirm(m1: list[dict], start_ts: int, end_ts: int, *, side: Side, lookback: int, buffer: float) -> bool:
    rows = [row for row in m1 if start_ts <= int(row["time"]) <= end_ts]
    if len(rows) < lookback + 2:
        return False
    for idx in range(lookback, len(rows)):
        prior = rows[idx - lookback : idx]
        bar = rows[idx]
        if side == "BUY" and float(bar["close"]) > max(float(row["high"]) for row in prior) + buffer:
            return True
        if side == "SELL" and float(bar["close"]) < min(float(row["low"]) for row in prior) - buffer:
            return True
    return False


def _simulate_trade(
    m1: list[dict],
    entry_index: int,
    *,
    symbol: str,
    side: Side,
    entry_price: float,
    sl: float,
    tp: float,
    max_hold_m1: int,
    sweep_type: str,
    zone_type: str,
) -> ResearchTrade:
    pip = _pip(symbol)
    risk_pips = abs(entry_price - sl) / pip
    exit_price = float(m1[min(entry_index + max_hold_m1, len(m1) - 1)]["close"])
    exit_time = int(m1[min(entry_index + max_hold_m1, len(m1) - 1)]["time"])
    reason = "time_exit"
    for row in m1[entry_index + 1 : min(len(m1), entry_index + max_hold_m1 + 1)]:
        high = float(row["high"])
        low = float(row["low"])
        exit_time = int(row["time"])
        if side == "BUY":
            if low <= sl:
                exit_price = sl
                reason = "stop_loss"
                break
            if high >= tp:
                exit_price = tp
                reason = "take_profit"
                break
        else:
            if high >= sl:
                exit_price = sl
                reason = "stop_loss"
                break
            if low <= tp:
                exit_price = tp
                reason = "take_profit"
                break

    pnl_pips = (exit_price - entry_price) / pip if side == "BUY" else (entry_price - exit_price) / pip
    return ResearchTrade(
        symbol=symbol,
        side=side,
        sweep_type=sweep_type,
        entry_time_utc=datetime.fromtimestamp(int(m1[entry_index]["time"]), timezone.utc).isoformat(),
        exit_time_utc=datetime.fromtimestamp(exit_time, timezone.utc).isoformat(),
        entry_price=float(entry_price),
        exit_price=float(exit_price),
        sl=float(sl),
        tp=float(tp),
        pnl_pips=float(pnl_pips),
        pnl_r=float(pnl_pips / max(risk_pips, 1e-10)),
        reason=reason,
        zone_type=zone_type,
    )


def run_research(
    *,
    symbol: str,
    start: datetime,
    end: datetime,
    rr: float,
    equal_lookback: int,
    equal_tolerance_pips: float,
    buffer_pips: float,
    bos_max_bars: int,
    retest_max_bars: int,
    max_hold_m1: int,
) -> list[ResearchTrade]:
    adapter = MT5Adapter()
    adapter.initialize()
    adapter.ensure_symbol(symbol)

    buffer_start = start - timedelta(days=7)
    m15 = _fetch_rates(adapter, symbol, "M15", buffer_start, end)
    m1 = _fetch_rates(adapter, symbol, "M1", buffer_start, end)
    m1_times = [int(row["time"]) for row in m1]
    pip = _pip(symbol)
    trades: list[ResearchTrade] = []
    busy_until = 0

    for idx in range(80, len(m15) - 1):
        if int(m15[idx]["time"]) < int(start.timestamp()) or int(m15[idx]["time"]) <= busy_until:
            continue

        sweep = _detect_sweep(
            m15,
            idx,
            pip=pip,
            equal_lookback=equal_lookback,
            equal_tolerance_pips=equal_tolerance_pips,
            buffer_pips=buffer_pips,
        )
        if sweep is None:
            continue
        side, sweep_type, _, sweep_extreme = sweep

        bos_index = 0
        for test_idx in range(idx + 1, min(len(m15), idx + 1 + bos_max_bars)):
            if _detect_bos(
                m15,
                test_idx,
                side=side,
                structure_lookback=6,
                impulse_lookback=8,
                impulse_range_multiple=1.15,
                body_ratio_min=0.45,
            ):
                bos_index = test_idx
                break
        if bos_index <= 0:
            continue

        zone_type, zone_low, zone_high = _find_zone(m15, bos_index, side=side)
        if not zone_type:
            continue

        for retest_idx in range(bos_index + 1, min(len(m15), bos_index + 1 + retest_max_bars)):
            retest = m15[retest_idx]
            touched = float(retest["high"]) >= zone_low and float(retest["low"]) <= zone_high
            if not touched:
                continue

            retest_start = int(retest["time"])
            retest_end = retest_start + 15 * 60
            if not _m1_bos_confirm(
                m1,
                retest_start,
                retest_end,
                side=side,
                lookback=5,
                buffer=buffer_pips * pip,
            ):
                continue

            m1_entry_idx = next((midx for midx, ts in enumerate(m1_times) if ts >= retest_end), None)
            if m1_entry_idx is None or m1_entry_idx >= len(m1):
                continue
            entry_price = float(m1[m1_entry_idx]["open"])
            if side == "BUY":
                sl = float(sweep_extreme - buffer_pips * pip)
                if entry_price <= sl:
                    continue
                tp = float(entry_price + (entry_price - sl) * rr)
            else:
                sl = float(sweep_extreme + buffer_pips * pip)
                if entry_price >= sl:
                    continue
                tp = float(entry_price - (sl - entry_price) * rr)

            trade = _simulate_trade(
                m1,
                m1_entry_idx,
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                sl=sl,
                tp=tp,
                max_hold_m1=max_hold_m1,
                sweep_type=sweep_type,
                zone_type=zone_type,
            )
            trades.append(trade)
            busy_until = int(datetime.fromisoformat(trade.exit_time_utc).timestamp())
            break

    return trades


def _print_summary(symbol: str, trades: list[ResearchTrade]) -> None:
    wins = [trade for trade in trades if trade.pnl_pips > 0]
    losses = [trade for trade in trades if trade.pnl_pips < 0]
    gross_win = sum(trade.pnl_pips for trade in wins)
    gross_loss = abs(sum(trade.pnl_pips for trade in losses))
    pf = gross_win / gross_loss if gross_loss else float("inf") if gross_win else 0.0
    net = sum(trade.pnl_pips for trade in trades)
    avg_r = sum(trade.pnl_r for trade in trades) / len(trades) if trades else 0.0
    print(
        f"{symbol}: trades={len(trades)} net_pips={net:.1f} "
        f"wins={len(wins)} losses={len(losses)} win_rate={(len(wins)/len(trades)*100 if trades else 0):.1f}% "
        f"PF={pf:.3f} avg_R={avg_r:.3f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Research HTF liquidity sweep -> BOS -> FVG/OB retest strategy.")
    parser.add_argument("--symbols", default="EURUSD", help="Comma-separated symbols")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--rr", type=float, default=2.0)
    parser.add_argument("--equal-lookback", type=int, default=32)
    parser.add_argument("--equal-tolerance-pips", type=float, default=1.0)
    parser.add_argument("--buffer-pips", type=float, default=0.3)
    parser.add_argument("--bos-max-bars", type=int, default=6)
    parser.add_argument("--retest-max-bars", type=int, default=12)
    parser.add_argument("--max-hold-m1", type=int, default=180)
    parser.add_argument("--csv", default="")
    args = parser.parse_args()

    start = _to_utc(args.start)
    end = _to_utc(args.end, end_of_day="T" not in args.end)
    all_trades: list[ResearchTrade] = []
    for symbol in [item.strip().upper() for item in args.symbols.split(",") if item.strip()]:
        trades = run_research(
            symbol=symbol,
            start=start,
            end=end,
            rr=float(args.rr),
            equal_lookback=int(args.equal_lookback),
            equal_tolerance_pips=float(args.equal_tolerance_pips),
            buffer_pips=float(args.buffer_pips),
            bos_max_bars=int(args.bos_max_bars),
            retest_max_bars=int(args.retest_max_bars),
            max_hold_m1=int(args.max_hold_m1),
        )
        _print_summary(symbol, trades)
        all_trades.extend(trades)

    if args.csv:
        path = Path(args.csv)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(ResearchTrade.__dataclass_fields__.keys()))
            writer.writeheader()
            for trade in all_trades:
                writer.writerow(asdict(trade))
        print(f"csv={path}")


if __name__ == "__main__":
    main()
