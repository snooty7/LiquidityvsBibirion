from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from src.services.config import AppConfig, load_config
from src.tools.backtest_mt5 import run_backtest


DEFAULT_MAGICS = [92001, 92008, 92009, 92010, 92014, 92015, 92016, 92017, 92018]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run branch-family research matrix for custom symbols")
    parser.add_argument("--config", default="config/settings.json", help="Path to bot config")
    parser.add_argument("--symbols", nargs="+", required=True, help="Symbols to test, e.g. BTC ETH")
    parser.add_argument("--start", required=True, help="UTC start date, e.g. 2026-01-07")
    parser.add_argument("--end", required=True, help="UTC end date, e.g. 2026-04-07")
    parser.add_argument("--magics", default=",".join(str(item) for item in DEFAULT_MAGICS), help="Comma-separated template magics")
    parser.add_argument("--csv", default="", help="Optional output CSV path")
    return parser.parse_args()


def _to_utc_day(value: str, *, end_of_day: bool = False) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if end_of_day:
        parsed = parsed.replace(hour=23, minute=59, second=59)
    return parsed.astimezone(timezone.utc)


def main() -> None:
    args = _parse_args()
    start_utc = _to_utc_day(args.start)
    end_utc = _to_utc_day(args.end, end_of_day=True)
    selected_magics = [int(item.strip()) for item in str(args.magics).split(",") if item.strip()]
    base_cfg = load_config(args.config)
    templates = [cfg for cfg in base_cfg.symbols if cfg.magic in selected_magics]
    templates.sort(key=lambda cfg: cfg.magic)

    rows: list[dict] = []
    for symbol in [str(item).upper() for item in args.symbols]:
        for template in templates:
            test_cfg = replace(template, symbol=symbol, magic=int(f"{template.magic}{len(symbol)}"))
            app_cfg = AppConfig(runtime=base_cfg.runtime, symbols=[test_cfg])
            result, _ = run_backtest(
                app_config=app_cfg,
                cfg=test_cfg,
                start_utc=start_utc,
                end_utc=end_utc,
                initial_equity=100000.0,
                side_mode="both",
                trades_csv=None,
            )
            row = {
                "symbol": symbol,
                "template_magic": template.magic,
                "timeframe": template.timeframe,
                "strategy_mode": template.strategy_mode,
                "confirmation_mode": template.confirmation_mode,
                "trades": result.total_trades,
                "win_rate_pct": round(result.win_rate_pct, 2),
                "net_pnl": round(result.net_pnl_money, 2),
                "avg_r": round(result.avg_r, 3),
                "pf": round(result.profit_factor, 3),
                "max_dd": round(result.max_drawdown_money, 2),
            }
            rows.append(row)
            print(
                f"{symbol} magic={template.magic} tf={template.timeframe} "
                f"strat={template.strategy_mode} trades={result.total_trades} "
                f"net={result.net_pnl_money:.2f} pf={result.profit_factor:.3f}"
            )

    if args.csv:
        output = Path(args.csv)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"csv={output}")


if __name__ == "__main__":
    main()
