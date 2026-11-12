"""Read-only financing snapshot and optional NZDUSD history extension from running MT5."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from src.backtesting.history import HistoricalData, load_history, save_history, validate_bars
from src.tools.backtest_mt5 import _fetch_chunked_rates

PAIRS = ("EURUSD", "GBPUSD", "NZDUSD", "USDCHF")


def exact_symbol(symbols, pair):
    """Resolve only a canonical name or one unambiguous suffix, never another FX pair."""
    exact = [s for s in symbols if s.name == pair]
    if exact:
        return exact[0]
    matches = [s for s in symbols if s.name.rstrip("-") == pair]
    if len(matches) != 1:
        raise ValueError(f"Unambiguous broker metadata required for {pair}")
    return matches[0]


def capture(root):
    """Attach to an existing safe session; no login, orders or live engine involved."""
    proc = subprocess.run(["powershell", "-NoProfile", "-Command",
        "Get-Process terminal64 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Path"],
        capture_output=True, text=True, check=True)
    paths = [p.strip() for p in proc.stdout.splitlines() if p.strip()]
    if len(paths) != 1:
        raise RuntimeError("One already-running terminal required")
    import MetaTrader5 as mt5
    def prohibited(*a, **k):
        raise RuntimeError("Trading prohibited in metadata/history capture")
    mt5.order_send = mt5.order_check = prohibited
    if not mt5.initialize(paths[0], timeout=10000):
        raise RuntimeError(f"Read-only connection failed: {mt5.last_error()}")
    try:
        terminal, account = mt5.terminal_info(), mt5.account_info()
        if terminal is None or account is None or not terminal.connected or terminal.trade_allowed:
            raise RuntimeError("Connected terminal with Algo Trading disabled required")
        if account.currency != "EUR":
            raise RuntimeError("EUR account metadata required")
        symbols = mt5.symbols_get()
        if symbols is None:
            raise RuntimeError("Symbol inventory unavailable")
        resolved = {p: exact_symbol(symbols, p) for p in PAIRS}
        keys = ("name", "swap_mode", "swap_long", "swap_short", "swap_rollover3days", "point", "digits",
                "trade_tick_value", "trade_tick_size", "currency_base", "currency_profit")
        snapshot = {"captured_at_utc": datetime.now(timezone.utc).isoformat(), "account_currency": account.currency,
            "autotrading": False, "trading_calls": False,
            "symbols": {p: {k: getattr(s, k) for k in keys} for p, s in resolved.items()}}
        root.mkdir(parents=True, exist_ok=True)
        (root/"FX_swap_snapshot_20261112.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        print("Saved four FX financing specifications without account identifiers", flush=True)
        output = root/"NZDUSD_extended.json"
        if output.exists():
            print("Existing NZDUSD extension preserved", flush=True)
            return
        # Retain the existing exported EUR valuation; no inferred price conversion
        # or zero current tick value can change the replay's monetary units.
        previous = load_history(root/"NZDUSD.json")["NZDUSD"]
        info = previous.symbol_info
        old_first, old_count = previous.bars("M1")[0]["time"], len(previous.bars("M1"))
        del previous
        name = resolved["NZDUSD"].name
        if not mt5.symbol_select(name, True):
            raise RuntimeError("Cannot select NZDUSD for read-only history")
        class Reader:
            def copy_rates_range(self, symbol, timeframe, start, end):
                rows = mt5.copy_rates_range(symbol, getattr(mt5, "TIMEFRAME_"+timeframe), start, end)
                if rows is None:
                    raise RuntimeError(f"History request failed for {symbol}/{timeframe}: {mt5.last_error()}")
                return rows
        start, end = datetime(2024, 10, 1, tzinfo=timezone.utc), datetime(2026, 11, 11, tzinfo=timezone.utc)
        rates = {}
        for tf in ("M1", "M30", "H1", "H4"):
            rates[tf] = validate_bars([b for b in _fetch_chunked_rates(Reader(), name, tf, start, end)
                                       if b["time"] < int(end.timestamp())], tf)
            print("NZDUSD", tf, len(rates[tf]), flush=True)
        if not rates["M1"]:
            raise RuntimeError("No NZDUSD M1 bars downloaded")
        extended = rates["M1"][0]["time"] <= old_first and len(rates["M1"]) >= old_count
        if not extended:
            output = root/"NZDUSD_partial_download_20261112.json"
        history = HistoricalData("NZDUSD", info, rates)
        save_history({"NZDUSD": history}, output)
        manifest = {"account_currency": "EUR", "broker_symbol": name, "history_digest": history.digest(),
                    "symbol_info": asdict(info), "valuation_basis": "Preserved existing EUR history export",
                    "first_utc": datetime.fromtimestamp(rates["M1"][0]["time"], timezone.utc).isoformat(),
                    "last_utc": datetime.fromtimestamp(rates["M1"][-1]["time"], timezone.utc).isoformat(),
                    "autotrading": False, "trading_calls": False}
        manifest["extends_existing_m1_history"] = extended
        manifest_path = root/("NZDUSD_extended_manifest.json" if extended else "NZDUSD_partial_download_manifest_20261112.json")
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print("Saved NZDUSD extension" if extended else "Shorter download archived separately; existing NZDUSD.json remains preferred", flush=True)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-root", type=Path, required=True)
    capture(parser.parse_args().history_root)
