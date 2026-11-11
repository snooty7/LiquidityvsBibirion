"""Cost-aware, chronological comparison of frozen strategy branch profiles.

Offline by default. The only MT5 access requires the explicit --mt5-history flag
and uses history/account-symbol metadata methods, never the trading engine.
"""
from __future__ import annotations

import argparse
import bisect
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
import math
from pathlib import Path
from typing import Callable

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import HistoricalData, fetch_mt5_history, load_history, save_history
from src.services.config import AppConfig, SymbolConfig, load_config
from src.tools.backtest_mt5 import ClosedTrade, run_backtest, _max_buffer_days


RISK_KEYS = (
    "daily_loss_limit_usd", "close_positions_on_daily_loss", "max_loss_per_trade_usd",
    "per_trade_loss_guard_mode", "per_trade_loss_risk_multiple", "max_profit_per_trade_usd",
    "trailing_stop_mode", "trailing_activation_r", "trailing_gap_r",
    "trailing_remove_tp_on_activation", "max_open_positions_total", "max_total_open_risk_pct",
    "news_filter_enabled", "news_provider", "news_block_minutes_before", "news_block_minutes_after",
)


def default_config_paths(root: Path = Path(".")) -> list[Path]:
    """Include deployed profiles and configured research branches, excluding templates."""
    configs = [path for path in (root / "config").glob("*.json")
               if "example" not in path.stem.lower() and not path.stem.endswith(".local")]
    return sorted([*configs, *(root / "live").glob("*/settings.json")])


@dataclass
class Branch:
    branch_id: str
    config: AppConfig
    symbol: SymbolConfig
    fingerprint: str
    sources: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Fold:
    index: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime

    def record(self) -> dict:
        """Serialize explicit half-open UTC windows."""
        return {"index": self.index, **{
            key: value.isoformat() for key, value in asdict(self).items() if key != "index"
        }}


def discover_branches(paths: list[Path]) -> list[Branch]:
    """Deduplicate identical behavior, preserving distinct settings for the same magic."""
    branches: dict[str, Branch] = {}
    for path in sorted(set(paths)):
        if not path.is_file():
            raise ValueError(f"Config does not exist: {path}")
        app = load_config(path)
        risk = {key: getattr(app.runtime, key) for key in RISK_KEYS}
        for cfg in app.symbols:
            serialized = json.dumps({"symbol": asdict(cfg), "runtime": risk}, sort_keys=True, allow_nan=False)
            digest = hashlib.sha256(serialized.encode()).hexdigest()
            if digest in branches:
                branches[digest].sources.append(str(path))
                continue
            identity = f"{cfg.magic}-{cfg.symbol}-{cfg.timeframe}-{digest[:8]}"
            # Notifications and live execution flags never apply to research.
            runtime = replace(app.runtime, dry_run=True, push_notifications_enabled=False)
            branches[digest] = Branch(identity, AppConfig(runtime, (cfg,)), cfg, digest, [str(path)])
    if not branches:
        raise ValueError("No branches were found in the requested configs")
    return sorted(branches.values(), key=lambda branch: branch.branch_id)


def make_folds(start: datetime, end: datetime, train_days: int = 90,
               test_days: int = 30, embargo_days: int = 1) -> list[Fold]:
    """Generate nonoverlapping test windows; all boundaries are exclusive on the right."""
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("Use an increasing timezone-aware UTC date range")
    if train_days <= 0 or test_days <= 0 or embargo_days < 0:
        raise ValueError("Train/test days must be positive; embargo must be nonnegative")
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    output = []
    test_start = start + timedelta(days=train_days + embargo_days)
    while test_start + timedelta(days=test_days) <= end:
        train_end = test_start - timedelta(days=embargo_days)
        output.append(Fold(len(output) + 1, train_end-timedelta(days=train_days), train_end,
                           test_start, test_start+timedelta(days=test_days)))
        test_start += timedelta(days=test_days)
    if not output:
        raise ValueError("Range is too short for one complete train/embargo/test fold")
    return output


def trade_metrics(trades: list[ClosedTrade], equity: float) -> dict:
    """Summarize net returns and reconstruct realized drawdown including entry costs."""
    net = sum(trade.pnl_money for trade in trades)
    wins = sum(trade.pnl_money > 0 for trade in trades)
    profit = sum(max(0.0, trade.pnl_money) for trade in trades)
    loss = -sum(min(0.0, trade.pnl_money) for trade in trades)
    events = []
    for trade in trades:
        # This model charges the same commission per side.
        entry_fee = trade.commission_cost_money / 2
        events.extend([(trade.entry_time_utc, -entry_fee),
                       (trade.exit_time_utc, trade.pnl_money+entry_fee)])
    balance = peak = equity
    drawdown = 0.0
    for _, amount in sorted(events, key=lambda event: event[0]):
        balance += amount
        peak = max(peak, balance)
        drawdown = max(drawdown, peak-balance)
    return {
        "trades": len(trades), "net_pnl": net, "return_pct": net/equity*100,
        "gross_pnl": sum(trade.gross_pnl_money for trade in trades),
        "spread_cost": sum(trade.spread_cost_money for trade in trades),
        "commission_cost": sum(trade.commission_cost_money for trade in trades),
        "slippage_cost": sum(trade.slippage_cost_money for trade in trades),
        "win_rate_pct": wins/len(trades)*100 if trades else 0.0,
        "profit_factor": profit/loss if loss > 0 else None,
        "profit_factor_note": "no losing trades" if profit > 0 and loss == 0 else "",
        "avg_r": sum(trade.pnl_r for trade in trades)/len(trades) if trades else 0.0,
        "max_realized_drawdown": drawdown,
    }


def history_coverage(history: HistoricalData, cfg: SymbolConfig, start: datetime, end: datetime,
                     *, max_gap_days: float = 3.0) -> str | None:
    """Require the full requested warm-up horizon and reject long holes in the window."""
    rows = history.bars("M1")
    start_ts, end_ts = int(start.timestamp()), int(end.timestamp())
    warmup = int((start-timedelta(days=_max_buffer_days(cfg))).timestamp())
    if not rows:
        return f"insufficient warm-up: need history from {datetime.fromtimestamp(warmup, timezone.utc).isoformat()}"
    times = history.timestamps("M1")
    relevant = times[bisect.bisect_left(times, start_ts):bisect.bisect_left(times, end_ts)]
    if len(relevant) < 10:
        return "fewer than 10 M1 bars in evaluation window"
    # The tolerance is explicit; holiday closures must not be filled with invented prices.
    boundaries = [start_ts, *relevant, end_ts]
    if not math.isfinite(max_gap_days) or max_gap_days <= 0:
        raise ValueError("Maximum history gap must be finite and positive")
    if any(right-left > max_gap_days*86400 for left, right in zip(boundaries, boundaries[1:])):
        return f"data gap exceeds {max_gap_days:g} calendar days within evaluation window"
    required = {cfg.timeframe: cfg.bars}
    if cfg.confirmation_mode != "none":
        required["M1"] = max(required.get("M1", 0), cfg.cisd_lookback_bars)
    if cfg.use_bias_filter or cfg.strategy_mode == "btc_mtf_trend_retest_reclaim":
        required[cfg.bias_timeframe] = max(required.get(cfg.bias_timeframe, 0),
                                           cfg.bias_lookback_bars, cfg.bias_ema_period+3)
    if cfg.strategy_mode == "btc_mtf_trend_retest_reclaim":
        required[cfg.setup_timeframe] = max(required.get(cfg.setup_timeframe, 0),
                                            cfg.setup_lookback_bars, cfg.ema_slow_period+3)
    from src.backtesting.history import TIMEFRAMES
    for timeframe, count in required.items():
        times = history.timestamps(timeframe)
        available = (bisect.bisect_right(times, start_ts-TIMEFRAMES[timeframe])
                     - bisect.bisect_left(times, warmup))
        if available < count:
            return f"insufficient warm-up bars: {timeframe} has {available}, requires {count}"
    return None


def evaluate(branches: list[Branch], histories: dict[str, HistoricalData], folds: list[Fold],
             costs: ExecutionCosts, *, initial_equity: float = 10000,
             min_train_trades: int = 20, runner: Callable = run_backtest,
             max_gap_days: float = 3.0) -> dict:
    """Freeze selection on training data, then compare every branch on unseen windows."""
    if not math.isfinite(initial_equity) or initial_equity <= 0 or min_train_trades < 1:
        raise ValueError("Positive equity and at least one training trade are required")
    if not branches or not folds:
        raise ValueError("At least one branch and fold are required")
    previous_end = None
    for fold in folds:
        if not fold.train_start < fold.train_end <= fold.test_start < fold.test_end:
            raise ValueError("Fold training must finish before its test window")
        if previous_end is not None and fold.test_start < previous_end:
            raise ValueError("Overlapping test windows would double count performance")
        previous_end = fold.test_end
    rows, selections = [], []
    all_oos: dict[str, list[ClosedTrade]] = {branch.branch_id: [] for branch in branches}
    selected_trades: list[ClosedTrade] = []
    successful_folds: dict[str, int] = {branch.branch_id: 0 for branch in branches}
    for fold in folds:
        training = {}
        def replay(branch: Branch, phase: str) -> dict:
            start, end = ((fold.train_start, fold.train_end) if phase == "train"
                          else (fold.test_start, fold.test_end))
            row = {"fold": fold.index, "phase": phase, "branch_id": branch.branch_id,
                   "start": start.isoformat(), "end_exclusive": end.isoformat()}
            history = histories.get(branch.symbol.symbol)
            reason = ("symbol history missing" if history is None else
                      history_coverage(history, branch.symbol, start, end, max_gap_days=max_gap_days))
            if reason:
                row.update(status="unavailable", reason=reason)
                rows.append(row)
                return row
            try:
                result, trades = runner(branch.config, branch.symbol, start, end,
                                        initial_equity=initial_equity, costs=costs,
                                        history=history, end_exclusive=True)
                # Guard the contract even when a custom/research runner is supplied.
                if any(not start <= datetime.fromisoformat(t.entry_time_utc) < end
                       or not datetime.fromisoformat(t.entry_time_utc) <= datetime.fromisoformat(t.exit_time_utc) <= end
                       for t in trades):
                    raise ValueError("Replay returned a trade outside its evaluation window")
                row.update(status="ok", metrics=trade_metrics(trades, initial_equity),
                           skipped_risk=result.skipped_risk)
                if phase == "test":
                    all_oos[branch.branch_id].extend(trades)
                    successful_folds[branch.branch_id] += 1
                    if branch.branch_id == selected:
                        selected_trades.extend(trades)
            except (ValueError, RuntimeError) as exc:
                row.update(status="error", reason=str(exc))
            rows.append(row)
            return row

        for branch in branches:
            training[branch.branch_id] = replay(branch, "train")
        eligible = [row for row in training.values() if row["status"] == "ok"
                    and row["metrics"]["trades"] >= min_train_trades and row["metrics"]["net_pnl"] > 0]
        eligible.sort(key=lambda row: (-row["metrics"]["return_pct"], row["branch_id"]))
        training_complete = all(row["status"] == "ok" for row in training.values())
        selected = eligible[0]["branch_id"] if eligible and training_complete else None
        selection = {"fold": fold.index, "selected_branch": selected,
                     "training_complete": training_complete,
                     "reason": "highest positive training net return among eligible branches" if selected
                     else "cash: no branch met the positive-net-return and minimum-trade criteria"}
        if not training_complete:
            selection["reason"] = "selection unavailable: training comparison has missing or failed branches"
        selections.append(selection)
        for branch in branches:
            row = replay(branch, "test")
            if branch.branch_id == selected:
                selection["test_status"] = row["status"]
                if row["status"] != "ok":
                    selection["reason"] += "; selected test unavailable, performance incomplete"
    summaries = [{"branch_id": branch.branch_id, "successful_test_folds": successful_folds[branch.branch_id],
                  "requested_test_folds": len(folds),
                  "metrics": (trade_metrics(all_oos[branch.branch_id], initial_equity)
                              if successful_folds[branch.branch_id] else None)} for branch in branches]
    # Incomplete branches are never advertised as performance winners.
    summaries.sort(key=lambda row: (row["successful_test_folds"] != len(folds),
                                    -row["metrics"]["net_pnl"] if row["metrics"] else 0, row["branch_id"]))
    return {"folds": [fold.record() for fold in folds], "rows": rows, "summaries": summaries,
            "selections": selections, "selected_oos": trade_metrics(selected_trades, initial_equity),
            "selected_oos_complete": all(s["training_complete"] and s.get("test_status", "ok") == "ok" for s in selections)}


def report_document(branches: list[Branch], costs: ExecutionCosts, histories: dict[str, HistoricalData],
                    evaluation: dict | None = None, *, initial_equity: float = 10000,
                    min_train_trades: int = 20, max_gap_days: float = 3.0) -> dict:
    """Build a reproducible report without exposing notification tokens or account secrets."""
    return {
        "schema_version": 1,
        "status": ("evaluated" if all(row["status"] == "ok" for row in evaluation["rows"])
                   else "partial_or_unavailable") if evaluation else "awaiting_history",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "costs": asdict(costs), "initial_equity_per_fold": initial_equity,
        "min_train_trades": min_train_trades,
        "coverage_max_gap_days": max_gap_days,
        "branches": [{"branch_id": branch.branch_id, "sources": branch.sources,
                      "fingerprint": branch.fingerprint, "settings": asdict(branch.symbol),
                      "risk_settings": {key: getattr(branch.config.runtime, key) for key in RISK_KEYS}}
                     for branch in branches],
        "history": {symbol: {"source": data.source, "sha256": data.digest(),
                              "m1_bars": len(data.rates["M1"]),
                              "start": datetime.fromtimestamp(data.rates["M1"][0]["time"], timezone.utc).isoformat(),
                              "end_exclusive": datetime.fromtimestamp(data.rates["M1"][-1]["time"]+60, timezone.utc).isoformat()}
                    for symbol, data in histories.items() if data.rates.get("M1")},
        "methodology": [
            "Frozen existing branch settings; no parameter optimization is performed.",
            "Rolling training, embargo, and nonoverlapping test windows use half-open UTC intervals.",
            "Each branch/fold starts flat with equal equity. Aggregate P&L sums independent fold results; it is not a compounded portfolio.",
            "Training picks highest positive net return with the minimum trade count; otherwise the selected track holds cash.",
            "All branch test results are descriptive comparisons, not inputs to that fold's selection.",
            "Bid OHLC; buys enter ask, sells exit ask. Historical spread is MT5 points; missing spread uses the explicit fallback.",
            "Adverse slippage on market/stop executions; take-profit limits have no adverse slippage. Stop gaps fill at the worse of stop/open.",
            "Commission is charged per lot per side on the relevant trading day. No swap/financing is modeled.",
            "OHLC replay cannot reconstruct intrabar ticks, latency, partial fills, or historical changes in account-currency tick valuation.",
            "Drawdown is based on realized cash flows including entry commissions, not intratrade mark-to-market equity.",
            "Branches are evaluated independently; simultaneous portfolio correlation/exposure is not modeled.",
            "Live news blackout is not replayed without an archived point-in-time news calendar.",
            "Out-of-sample means withheld from this evaluation; prior manual tuning on the same dates cannot be ruled out.",
        ],
        "evaluation": evaluation,
    }


def write_report(document: dict, output: Path) -> tuple[Path, Path]:
    """Write strict JSON and a standalone readable HTML comparison report."""
    output.mkdir(parents=True, exist_ok=True)
    json_path, html_path = output / "report.json", output / "report.html"
    json_path.write_text(json.dumps(document, indent=2, allow_nan=False), encoding="utf-8")
    esc = lambda value: html.escape(str(value))
    def table(headers: list[str], rows: list[list]) -> str:
        return "<table><thead><tr>"+"".join(f"<th>{esc(h)}</th>" for h in headers)+"</tr></thead><tbody>"+"".join(
            "<tr>"+"".join(f"<td>{esc(v)}</td>" for v in row)+"</tr>" for row in rows)+"</tbody></table>"
    body = "<h1>Cost-aware walk-forward branch comparison</h1>"
    body += f"<p>Status: <strong>{esc(document['status'])}</strong> · Generated {esc(document['generated_at_utc'])}</p>"
    body += "<p>Costs are explicit research assumptions, not verified broker charges. No profitability claim or live-trading recommendation is made.</p>"
    if document.get("account_currency"):
        body += f"<p>Account/report currency: <strong>{esc(document['account_currency'])}</strong>. Maximum permitted history gap: {esc(document['coverage_max_gap_days'])} calendar days.</p>"
    if document.get("run_notes"):
        body += "<ul>"+"".join(f"<li>{esc(note)}</li>" for note in document["run_notes"])+"</ul>"
    if document.get("data_acquisition"):
        body += "<h2>Broker history acquisition</h2>"+table(
            ["Configured symbol", "Broker symbol", "Status", "M1 bars", "Reason"],
            [[symbol, item.get("broker_symbol", "—"), item["status"], item.get("bars", "—"), item.get("reason", "")]
             for symbol, item in document["data_acquisition"]["symbols"].items()])
    body += "<h2>Execution assumptions</h2>"+table(["Setting", "Value"], list(document["costs"].items()))
    body += "<h2>Existing branch profiles</h2>"+table(
        ["Branch", "Strategy", "Confirmation", "Risk %", "Sources"],
        [[b["branch_id"], b["settings"]["strategy_mode"], b["settings"]["confirmation_mode"],
          b["settings"]["risk_pct"], ", ".join(b["sources"])] for b in document["branches"]])
    evaluation = document["evaluation"]
    if evaluation:
        body += "<h2>Out-of-sample comparison</h2>"+table(
            ["Branch", "Complete folds", "Trades", "Gross", "Spread", "Commission", "Slippage", "Net", "Avg R", "Realized DD"],
            [[r["branch_id"], f"{r['successful_test_folds']}/{r['requested_test_folds']}",
              r["metrics"]["trades"] if r["metrics"] else "unavailable",
              *[round(r["metrics"][key], 4) if r["metrics"] else "unavailable" for key in ("gross_pnl", "spread_cost", "commission_cost", "slippage_cost", "net_pnl", "avg_r", "max_realized_drawdown")]]
             for r in evaluation["summaries"]])
        body += "<h2>Training-only selections</h2>"+table(
            ["Fold", "Selected branch", "Test status", "Reason"],
            [[s["fold"], s["selected_branch"] or "CASH", s.get("test_status", "cash"), s["reason"]] for s in evaluation["selections"]])
        body += f"<p>Selected OOS track: net {evaluation['selected_oos']['net_pnl']:.4f}; complete: {evaluation['selected_oos_complete']}.</p>"
        if document.get("available_instruments_selection"):
            available = document["available_instruments_selection"]
            body += f"<h2>Available-instrument cohort</h2><p>This separate selection compares {esc(available['branch_profiles'])} profiles, excluding {esc(', '.join(available['excluded_symbols']))}. The full comparison above retains every requested profile.</p>"
            body += f"<p>Training-selected OOS net: {available['selected_oos']['net_pnl']:.4f}; complete: {available['selected_oos_complete']}.</p>"
            body += table(["Fold", "Training-selected branch", "Test status", "Reason"],
                          [[s["fold"],s["selected_branch"] or "CASH",s.get("test_status","cash"),s["reason"]]
                           for s in available["selections"]])
        body += "<h2>Window boundaries (end exclusive)</h2>"+table(
            ["Fold", "Train start", "Train end", "Test start", "Test end"],
            [[f[k] for k in ("index", "train_start", "train_end", "test_start", "test_end")] for f in evaluation["folds"]])
        body += "<h2>Per-window results and data failures</h2>"+table(
            ["Fold", "Phase", "Branch", "Status", "Trades", "Risk skips", "Net", "Reason"],
            [[r["fold"], r["phase"], r["branch_id"], r["status"], r.get("metrics", {}).get("trades", "—"),
              r.get("skipped_risk", "—"),
              round(r["metrics"]["net_pnl"], 4) if "metrics" in r else "—", r.get("reason", "")] for r in evaluation["rows"]])
    else:
        body += "<h2>Data needed before comparison</h2><p>No suitable full historical dataset was supplied. Profitability metrics have not been calculated. Supply a bid-OHLC JSON bundle or explicitly fetch read-only MT5 history. Default windows are 90 training days, one embargo day, and 30 test days.</p>"
    body += "<h2>Methodology and limits</h2><ul>"+"".join(f"<li>{esc(item)}</li>" for item in document["methodology"])+"</ul>"
    html_path.write_text("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                         "<title>Walk-forward evaluation</title><style>body{font:15px system-ui;max-width:1500px;margin:40px auto;padding:0 20px;color:#172334;background:#f7f9fc}"
                         "table{border-collapse:collapse;background:white;display:block;overflow:auto;margin:20px 0}th,td{padding:10px;border:1px solid #d5dce5;text-align:left}th{background:#e9eef7}li{margin:8px 0}h2{margin-top:36px}</style>"+body+"</html>", encoding="utf-8")
    return json_path, html_path


def utc_date(value: str) -> datetime:
    """Parse a UTC date or timezone-aware timestamp."""
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configs", nargs="+", type=Path)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--history", type=Path, help="Offline bid-OHLC JSON bundle")
    source.add_argument("--mt5-history", action="store_true", help="Explicit read-only history connection; never sends orders")
    parser.add_argument("--save-history", type=Path)
    parser.add_argument("--start", type=utc_date, help="Start of first training window (UTC)")
    parser.add_argument("--end", type=utc_date, help="Exclusive end of evaluation (UTC)")
    parser.add_argument("--train-days", type=int, default=90)
    parser.add_argument("--test-days", type=int, default=30)
    parser.add_argument("--embargo-days", type=int, default=1)
    parser.add_argument("--min-train-trades", type=int, default=20)
    parser.add_argument("--max-gap-days", type=float, default=3.0,
                        help="Explicit maximum calendar gap in M1 history, including market closures")
    parser.add_argument("--initial-equity", type=float, default=10000)
    parser.add_argument("--spread-mode", choices=["historical", "fixed"], default="historical")
    parser.add_argument("--spread-pips", type=float, default=1.0, help="Fixed spread or fallback for missing historical spreads")
    parser.add_argument("--commission-per-lot", type=float, default=3.5, help="Account-currency units per lot per side")
    parser.add_argument("--slippage-pips", type=float, default=.2)
    parser.add_argument("--output", type=Path, default=Path("reports/walk_forward"))
    args = parser.parse_args()
    paths = args.configs or default_config_paths()
    branches = discover_branches(paths)
    costs = ExecutionCosts(args.spread_mode, args.spread_pips, args.commission_per_lot, args.slippage_pips)
    histories, evaluation = {}, None
    if args.history or args.mt5_history:
        if not args.start or not args.end:
            parser.error("--start and --end are required for evaluation")
        folds = make_folds(args.start, args.end, args.train_days, args.test_days, args.embargo_days)
        histories = (load_history(args.history) if args.history else
                     fetch_mt5_history([branch.symbol for branch in branches], args.start, args.end))
        if args.save_history:
            save_history(histories, args.save_history)
        evaluation = evaluate(branches, histories, folds, costs, initial_equity=args.initial_equity,
                              min_train_trades=args.min_train_trades, max_gap_days=args.max_gap_days)
    document = report_document(branches, costs, histories, evaluation,
                               initial_equity=args.initial_equity, min_train_trades=args.min_train_trades,
                               max_gap_days=args.max_gap_days)
    for path in write_report(document, args.output):
        print(path.resolve())


if __name__ == "__main__":
    main()
