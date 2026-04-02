from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from dataclasses import asdict, dataclass, fields, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from src.engine.orchestrator import TIMEFRAME_SECONDS, branch_id
from src.execution.mt5_adapter import MT5Adapter
from src.persistence.repository import SQLiteRepository
from src.risk.sizing import SymbolTradeInfo
from src.services.config import AppConfig, SymbolConfig, load_config
from src.tools.backtest_mt5 import (
    ClosedTrade,
    OpenTrade,
    _apply_open_trade_bar,
    _build_entry_trade,
    _fetch_chunked_rates,
)


@dataclass(frozen=True)
class NearTradeTimeline:
    stage: str
    anchor_time_utc: str
    anchor_reason: str
    confirmed_at_utc: Optional[str]
    canceled_at_utc: Optional[str]
    canceled_reason: Optional[str]


@dataclass(frozen=True)
class NearTradeRow:
    setup_id: str
    symbol: str
    timeframe: str
    magic: int
    branch_id: str
    strategy_mode: str
    side: str
    status: str
    created_at_utc: str
    stage: str
    anchor_reason: str
    anchor_time_utc: str
    confirmed_at_utc: str
    terminal_reason: str
    entry_time_utc: str
    entry_price: float
    exit_time_utc: str
    exit_price: float
    outcome: str
    pnl_pips: float
    pnl_r: float
    mfe_pips: float
    mae_pips: float
    sl_pips: float
    tp_pips: float
    note: str


def _local_day_bounds_utc(target_day: date, tz_name: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(tz_name)
    start_local = datetime.combine(target_day, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _parse_target_day(day_raw: str, tz_name: str) -> tuple[date, datetime, datetime]:
    target_day = date.fromisoformat(day_raw)
    start_utc, end_utc = _local_day_bounds_utc(target_day, tz_name)
    return target_day, start_utc, end_utc


def _load_non_executed_day_setups(
    conn: sqlite3.Connection,
    day_start_utc: datetime,
    day_end_utc: datetime,
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT *
        FROM pending_setups
        WHERE created_at >= ? AND created_at < ? AND executed_ticket IS NULL
        ORDER BY created_at ASC
        """,
        (day_start_utc.isoformat(), day_end_utc.isoformat()),
    ).fetchall()


def _load_events_for_setup_ids(conn: sqlite3.Connection, setup_ids: list[str]) -> dict[str, list[sqlite3.Row]]:
    if not setup_ids:
        return {}
    placeholders = ",".join("?" for _ in setup_ids)
    rows = conn.execute(
        f"""
        SELECT *
        FROM persisted_events
        WHERE setup_id IN ({placeholders})
        ORDER BY created_at_utc ASC, event_id ASC
        """,
        tuple(setup_ids),
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(str(row["setup_id"]), []).append(row)
    return grouped


def _build_timeline(setup_row: sqlite3.Row, events: list[sqlite3.Row]) -> NearTradeTimeline:
    created_at = str(setup_row["created_at"])
    status = str(setup_row["status"])
    confirmed_at: Optional[str] = None
    canceled_at: Optional[str] = None
    canceled_reason: Optional[str] = None

    for row in events:
        event_type = str(row["event_type"])
        if event_type == "SETUP_CONFIRMED" and confirmed_at is None:
            confirmed_at = str(row["created_at_utc"])
        if event_type in {"STALE_PENDING_CANCELED", "SKIP_BIAS", "SKIP_SPREAD", "SKIP_ORDER_BLOCK", "SKIP_PORTFOLIO_CAP", "SKIP_DUPLICATE_SETUP"}:
            canceled_at = str(row["created_at_utc"])
            canceled_reason = event_type

    if confirmed_at is not None:
        stage = "confirmed"
        anchor_time = confirmed_at
        anchor_reason = "confirmed"
    else:
        stage = "pending_only"
        anchor_time = created_at
        anchor_reason = "pending_created"

    if status == "CANCELED" and canceled_reason is None:
        canceled_at = str(setup_row["updated_at"])
        closed_reason = setup_row["closed_reason"]
        canceled_reason = str(closed_reason or "canceled")
    elif status in {"EXPIRED", "REJECTED", "FAILED"} and canceled_reason is None:
        canceled_at = str(setup_row["updated_at"])
        closed_reason = setup_row["closed_reason"]
        canceled_reason = str(closed_reason or status.lower())

    return NearTradeTimeline(
        stage=stage,
        anchor_time_utc=anchor_time,
        anchor_reason=anchor_reason,
        confirmed_at_utc=confirmed_at,
        canceled_at_utc=canceled_at,
        canceled_reason=canceled_reason,
    )


def _cfg_from_context(base_cfg: SymbolConfig, context: dict) -> SymbolConfig:
    risk = dict(context.get("risk") or {})
    sl_pips = float(risk.get("sl_pips", base_cfg.sl_pips))
    tp_pips = float(risk.get("tp_pips", base_cfg.tp_pips))
    rr = base_cfg.rr
    if sl_pips > 0:
        rr = tp_pips / sl_pips
    risk_pct = float(risk.get("risk_pct", base_cfg.risk_pct))
    return replace(base_cfg, sl_pips=sl_pips, rr=rr, risk_pct=risk_pct)


def _select_entry_bar(m1_rates: list[dict], anchor_ts: int) -> tuple[int, dict] | tuple[None, None]:
    for idx, bar in enumerate(m1_rates):
        close_time = int(bar["time"]) + TIMEFRAME_SECONDS["M1"]
        if close_time > anchor_ts:
            return idx, bar
    return None, None


def _track_excursions(trade: OpenTrade, bar: dict, pip: float, mfe_pips: float, mae_pips: float) -> tuple[float, float]:
    high = float(bar["high"])
    low = float(bar["low"])
    if trade.side == "BUY":
        favorable = max(0.0, (high - trade.entry_price) / pip)
        adverse = max(0.0, (trade.entry_price - low) / pip)
    else:
        favorable = max(0.0, (trade.entry_price - low) / pip)
        adverse = max(0.0, (high - trade.entry_price) / pip)
    return max(mfe_pips, favorable), max(mae_pips, adverse)


def _simulate_setup(
    app_config: AppConfig,
    cfg: SymbolConfig,
    symbol_info: SymbolTradeInfo,
    m1_rates: list[dict],
    timeline: NearTradeTimeline,
    row: sqlite3.Row,
    context: dict,
    equity: float,
    horizon_end_utc: datetime,
) -> NearTradeRow:
    anchor_dt = datetime.fromisoformat(timeline.anchor_time_utc).astimezone(timezone.utc)
    entry_idx, entry_bar = _select_entry_bar(m1_rates, int(anchor_dt.timestamp()))
    terminal_reason = str(row["closed_reason"] or timeline.canceled_reason or "")
    signal = dict(context.get("signal") or {})
    side = str(signal.get("side") or row["side"] or "").upper()
    if entry_bar is None or not side:
        return NearTradeRow(
            setup_id=str(row["setup_id"]),
            symbol=str(row["symbol"]),
            timeframe=str(row["timeframe"]),
            magic=int(context.get("magic") or 0),
            branch_id=str(context.get("branch_id") or ""),
            strategy_mode=str(context.get("strategy_mode") or ""),
            side=side,
            status=str(row["status"]),
            created_at_utc=str(row["created_at"]),
            stage=timeline.stage,
            anchor_reason=timeline.anchor_reason,
            anchor_time_utc=timeline.anchor_time_utc,
            confirmed_at_utc=timeline.confirmed_at_utc or "",
            terminal_reason=terminal_reason,
            entry_time_utc="",
            entry_price=0.0,
            exit_time_utc="",
            exit_price=0.0,
            outcome="insufficient_m1_history",
            pnl_pips=0.0,
            pnl_r=0.0,
            mfe_pips=0.0,
            mae_pips=0.0,
            sl_pips=float(cfg.sl_pips),
            tp_pips=float(cfg.tp_pips),
            note="No closed M1 bar available after anchor time.",
        )

    entry_time = int(entry_bar["time"]) + TIMEFRAME_SECONDS["M1"]
    entry_price = float(entry_bar["close"])
    signal_key = str(signal.get("semantic_key") or signal.get("signal_key") or row["signal_key"])
    trade = _build_entry_trade(
        cfg,
        app_config.runtime,
        symbol_info,
        float(equity),
        side,
        entry_time,
        entry_price,
        signal_key,
        timeline.anchor_reason,
    )

    pip = MT5Adapter.pip_size(symbol_info)
    closed: Optional[ClosedTrade] = None
    mfe_pips = 0.0
    mae_pips = 0.0
    horizon_ts = int(horizon_end_utc.timestamp())

    for bar in m1_rates[entry_idx + 1 :]:
        bar_close = int(bar["time"]) + TIMEFRAME_SECONDS["M1"]
        if bar_close > horizon_ts:
            break
        mfe_pips, mae_pips = _track_excursions(trade, bar, pip, mfe_pips, mae_pips)
        trade, closed = _apply_open_trade_bar(cfg, app_config.runtime, trade, bar, symbol_info)
        if closed is not None:
            break

    if closed is None:
        last_bar = None
        for bar in reversed(m1_rates):
            if int(bar["time"]) + TIMEFRAME_SECONDS["M1"] <= horizon_ts:
                last_bar = bar
                break
        if last_bar is None:
            outcome = "no_horizon_bar"
            exit_time_utc = ""
            exit_price = 0.0
            pnl_pips = 0.0
            pnl_r = 0.0
        else:
            mfe_pips, mae_pips = _track_excursions(trade, last_bar, pip, mfe_pips, mae_pips)
            exit_price = float(last_bar["close"])
            exit_time_utc = datetime.fromtimestamp(int(last_bar["time"]) + TIMEFRAME_SECONDS["M1"], timezone.utc).isoformat()
            pnl_signed = (exit_price - trade.entry_price) / pip if trade.side == "BUY" else (trade.entry_price - exit_price) / pip
            pnl_pips = float(pnl_signed)
            pnl_r = pnl_pips / float(cfg.sl_pips) if cfg.sl_pips > 0 else 0.0
            outcome = "mark_to_horizon"
        return NearTradeRow(
            setup_id=str(row["setup_id"]),
            symbol=str(row["symbol"]),
            timeframe=str(row["timeframe"]),
            magic=int(context.get("magic") or 0),
            branch_id=str(context.get("branch_id") or ""),
            strategy_mode=str(context.get("strategy_mode") or ""),
            side=side,
            status=str(row["status"]),
            created_at_utc=str(row["created_at"]),
            stage=timeline.stage,
            anchor_reason=timeline.anchor_reason,
            anchor_time_utc=timeline.anchor_time_utc,
            confirmed_at_utc=timeline.confirmed_at_utc or "",
            terminal_reason=terminal_reason,
            entry_time_utc=datetime.fromtimestamp(entry_time, timezone.utc).isoformat(),
            entry_price=entry_price,
            exit_time_utc=exit_time_utc,
            exit_price=exit_price,
            outcome=outcome,
            pnl_pips=round(pnl_pips, 2),
            pnl_r=round(pnl_r, 3),
            mfe_pips=round(mfe_pips, 2),
            mae_pips=round(mae_pips, 2),
            sl_pips=float(cfg.sl_pips),
            tp_pips=float(cfg.tp_pips),
            note="Trade was still open at analysis horizon.",
        )

    pnl_pips = float(closed.pnl_r * cfg.sl_pips)
    return NearTradeRow(
        setup_id=str(row["setup_id"]),
        symbol=str(row["symbol"]),
        timeframe=str(row["timeframe"]),
        magic=int(context.get("magic") or 0),
        branch_id=str(context.get("branch_id") or ""),
        strategy_mode=str(context.get("strategy_mode") or ""),
        side=side,
        status=str(row["status"]),
        created_at_utc=str(row["created_at"]),
        stage=timeline.stage,
        anchor_reason=timeline.anchor_reason,
        anchor_time_utc=timeline.anchor_time_utc,
        confirmed_at_utc=timeline.confirmed_at_utc or "",
        terminal_reason=terminal_reason,
        entry_time_utc=closed.entry_time_utc,
        entry_price=float(closed.entry_price),
        exit_time_utc=closed.exit_time_utc,
        exit_price=float(closed.exit_price),
        outcome=str(closed.reason),
        pnl_pips=round(pnl_pips, 2),
        pnl_r=round(float(closed.pnl_r), 3),
        mfe_pips=round(mfe_pips, 2),
        mae_pips=round(mae_pips, 2),
        sl_pips=float(cfg.sl_pips),
        tp_pips=float(cfg.tp_pips),
        note="",
    )


def _write_rows_csv(path: Path, rows: list[NearTradeRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [item.name for item in fields(NearTradeRow)]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def _summarize_by_branch(rows: list[NearTradeRow]) -> dict[str, dict[str, object]]:
    summary: dict[str, dict[str, object]] = {}
    for row in rows:
        key = f"{row.symbol} {row.timeframe} magic={row.magic}"
        item = summary.setdefault(
            key,
            {
                "count": 0,
                "confirmed": 0,
                "pending_only": 0,
                "pnl_pips": 0.0,
                "outcomes": {},
            },
        )
        item["count"] = int(item["count"]) + 1
        if row.stage == "confirmed":
            item["confirmed"] = int(item["confirmed"]) + 1
        else:
            item["pending_only"] = int(item["pending_only"]) + 1
        item["pnl_pips"] = float(item["pnl_pips"]) + float(row.pnl_pips)
        outcomes = dict(item["outcomes"])
        outcomes[row.outcome] = int(outcomes.get(row.outcome, 0)) + 1
        item["outcomes"] = outcomes
    return summary


def run_analysis(
    config_path: str,
    target_day_raw: str,
    tz_name: str,
    equity: float,
    csv_path: Optional[Path],
    *,
    confirmed_only: bool = False,
) -> int:
    app_config = load_config(config_path)
    repo = SQLiteRepository(app_config.runtime.db_path)
    repo.conn.row_factory = sqlite3.Row
    target_day, day_start_utc, day_end_utc = _parse_target_day(target_day_raw, tz_name)
    now_utc = datetime.now(timezone.utc)
    horizon_end_utc = min(day_end_utc, now_utc)

    setup_rows = _load_non_executed_day_setups(repo.conn, day_start_utc, day_end_utc)
    setup_ids = [str(row["setup_id"]) for row in setup_rows]
    events_by_setup = _load_events_for_setup_ids(repo.conn, setup_ids)

    actual_trade_count = repo.conn.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM persisted_events
        WHERE event_type = 'TRADE_OK' AND created_at_utc >= ? AND created_at_utc < ?
        """,
        (day_start_utc.isoformat(), day_end_utc.isoformat()),
    ).fetchone()["cnt"]

    cfg_by_branch = {branch_id(cfg): cfg for cfg in app_config.symbols}

    setups_for_symbol: dict[str, list[tuple[sqlite3.Row, dict, NearTradeTimeline, SymbolConfig]]] = {}
    for row in setup_rows:
        context = json.loads(str(row["context_json"] or "{}"))
        current_branch = str(context.get("branch_id") or "")
        cfg = cfg_by_branch.get(current_branch)
        if cfg is None:
            continue
        effective_cfg = _cfg_from_context(cfg, context)
        timeline = _build_timeline(row, events_by_setup.get(str(row["setup_id"]), []))
        if confirmed_only and timeline.stage != "confirmed":
            continue
        setups_for_symbol.setdefault(effective_cfg.symbol, []).append((row, context, timeline, effective_cfg))

    analysis_rows: list[NearTradeRow] = []
    if setups_for_symbol:
        adapter = MT5Adapter(default_deviation=app_config.runtime.default_deviation)
        adapter.initialize()
        try:
            for symbol, items in setups_for_symbol.items():
                symbol_info = SymbolTradeInfo.from_mt5(adapter.symbol_info(symbol))
                min_anchor = min(datetime.fromisoformat(item[2].anchor_time_utc).astimezone(timezone.utc) for item in items)
                fetch_start = min_anchor - timedelta(hours=2)
                m1_rates = _fetch_chunked_rates(adapter, symbol, "M1", fetch_start, horizon_end_utc + timedelta(minutes=1))
                for row, context, timeline, effective_cfg in items:
                    analysis_rows.append(
                        _simulate_setup(
                            app_config,
                            effective_cfg,
                            symbol_info,
                            m1_rates,
                            timeline,
                            row,
                            context,
                            equity,
                            horizon_end_utc,
                        )
                    )
        finally:
            adapter.shutdown()

    if csv_path is None:
        csv_path = Path("reports") / f"day_near_trades_{target_day.isoformat()}.csv"
    _write_rows_csv(csv_path, analysis_rows)

    confirmed_count = sum(1 for row in analysis_rows if row.stage == "confirmed")
    pending_only_count = sum(1 for row in analysis_rows if row.stage != "confirmed")
    outcome_counts: dict[str, int] = {}
    for row in analysis_rows:
        outcome_counts[row.outcome] = outcome_counts.get(row.outcome, 0) + 1
    branch_summary = _summarize_by_branch(analysis_rows)

    print(f"Day: {target_day.isoformat()} ({tz_name})")
    print(f"UTC window: {day_start_utc.isoformat()} -> {day_end_utc.isoformat()}")
    print(f"Actual TRADE_OK count: {int(actual_trade_count)}")
    print(f"Near-trade setups not executed: {len(analysis_rows)}")
    print(f"Confirmed but not executed: {confirmed_count}")
    print(f"Pending-only / never confirmed: {pending_only_count}")
    print(f"Analysis horizon end UTC: {horizon_end_utc.isoformat()}")
    print("")
    print("Outcome counts:")
    if outcome_counts:
        for key in sorted(outcome_counts):
            print(f"  {key}: {outcome_counts[key]}")
    else:
        print("  none")
    print("")
    print("By branch:")
    if branch_summary:
        for key in sorted(branch_summary):
            item = branch_summary[key]
            outcomes = ", ".join(f"{name}={count}" for name, count in sorted(dict(item["outcomes"]).items()))
            print(
                f"  {key}: setups={item['count']} confirmed={item['confirmed']} pending_only={item['pending_only']} "
                f"net_pips={float(item['pnl_pips']):.2f} outcomes=[{outcomes}]"
            )
    else:
        print("  none")
    print("")
    print(f"CSV: {csv_path}")
    print("")
    for row in analysis_rows:
        print(
            f"{row.created_at_utc} {row.symbol} {row.timeframe} magic={row.magic} {row.side} "
            f"stage={row.stage} status={row.status} outcome={row.outcome} "
            f"pnl_pips={row.pnl_pips:.2f} pnl_r={row.pnl_r:.3f} mfe={row.mfe_pips:.2f} mae={row.mae_pips:.2f} "
            f"terminal={row.terminal_reason or '-'} setup_id={row.setup_id}"
        )

    repo.close()
    return 0


def main() -> int:
    default_day = datetime.now(ZoneInfo("Europe/Sofia")).date().isoformat()
    parser = argparse.ArgumentParser(description="Analyze today's non-executed setups and simulate what-if outcomes.")
    parser.add_argument("--config", default="config/settings.json", help="Path to bot config.")
    parser.add_argument("--date", default=default_day, help="Target local day in YYYY-MM-DD.")
    parser.add_argument("--timezone", default="Europe/Sofia", help="Local timezone for day boundaries.")
    parser.add_argument("--equity", type=float, default=100000.0, help="Equity used for what-if volume sizing.")
    parser.add_argument("--csv", default="", help="Optional CSV output path.")
    parser.add_argument("--confirmed-only", action="store_true", help="Analyze only setups that reached SETUP_CONFIRMED.")
    args = parser.parse_args()

    csv_path = Path(args.csv) if args.csv else None
    return run_analysis(
        args.config,
        args.date,
        args.timezone,
        float(args.equity),
        csv_path,
        confirmed_only=bool(args.confirmed_only),
    )


if __name__ == "__main__":
    raise SystemExit(main())
