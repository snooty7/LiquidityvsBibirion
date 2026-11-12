"""Read USDCHF financing metadata from an already-running MT5; never send orders."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess


def capture(output: Path):
    """Attach to the sole running terminal and refuse an unsafe or disconnected state."""
    # Discover the existing process so initialize cannot silently start another
    # terminal/profile. No login/password/account identifiers are accepted or saved.
    result = subprocess.run(["powershell", "-NoProfile", "-Command",
        "Get-Process terminal64 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Path"],
        capture_output=True, text=True, check=True)
    paths = [p.strip() for p in result.stdout.splitlines() if p.strip()]
    if len(paths) != 1:
        raise RuntimeError("Exactly one already-running MT5 terminal required")
    import MetaTrader5 as mt5
    def prohibited(*args, **kwargs):
        raise RuntimeError("Trading is prohibited in metadata capture")
    mt5.order_send = mt5.order_check = prohibited
    if not mt5.initialize(paths[0], timeout=10000):
        raise RuntimeError(f"MT5 metadata connection failed: {mt5.last_error()}")
    try:
        terminal, account = mt5.terminal_info(), mt5.account_info()
        if terminal is None or account is None or not terminal.connected or terminal.trade_allowed:
            raise RuntimeError("Connected MT5 with Algo Trading disabled required")
        symbols = mt5.symbols_get("*USDCHF*")
        if not symbols:
            raise RuntimeError("USDCHF metadata unavailable")
        keys = ("name", "swap_mode", "swap_long", "swap_short", "swap_rollover3days", "point",
                "digits", "trade_tick_value", "trade_tick_size", "currency_profit")
        snapshot = {"captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "account_currency": account.currency, "autotrading": False,
            "symbols": [{k: getattr(s, k) for k in keys} for s in symbols]}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        print("Saved financing metadata without account identifiers:", output)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    capture(parser.parse_args().output)
