from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = Path(__file__).resolve().parent
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from argparse import ArgumentParser
from datetime import datetime, timezone
import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import parse_qs, urlparse

from dashboard.data import TIMEFRAME_WINDOWS, bars_for_window, event_rows_for_symbol, load_recent_event_rows, recent_signal_cards, timeframe_markers
from src.execution.mt5_adapter import MT5Adapter
from src.services.config import load_config


CSV_PATH = REPO_ROOT / "bot_events.csv"
CONFIG_PATH = REPO_ROOT / "config" / "settings.json"
STATIC_FILES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/styles.css": "styles.css",
    "/app.js": "app.js",
}


class DashboardState:
    def __init__(self, config_path: Path, csv_path: Path) -> None:
        self.config_path = config_path
        self.csv_path = csv_path
        self.app_config = load_config(config_path)
        self.symbols = sorted({cfg.symbol for cfg in self.app_config.symbols})
        self.adapter = MT5Adapter(default_deviation=self.app_config.runtime.default_deviation)
        self._lock = Lock()
        with self._lock:
            self.adapter.initialize()

    def close(self) -> None:
        with self._lock:
            self.adapter.shutdown()

    def build_snapshot(self, symbol: str) -> dict:
        now_utc = datetime.now(timezone.utc)
        rows = load_recent_event_rows(self.csv_path, limit=6000)
        filtered_rows = event_rows_for_symbol(rows, symbol)
        result = {
            "generated_at_utc": now_utc.isoformat(),
            "symbol": symbol.upper(),
            "symbols": self.symbols,
            "timeframes": {},
            "recentSignals": recent_signal_cards(filtered_rows),
        }
        for timeframe, window in TIMEFRAME_WINDOWS.items():
            start_utc = now_utc - window
            with self._lock:
                rates = self.adapter.copy_rates(symbol.upper(), timeframe, bars_for_window(timeframe))
            candles = []
            for row in rates:
                row_ts = datetime.fromtimestamp(int(row["time"]), tz=timezone.utc)
                if row_ts < start_utc:
                    continue
                candles.append(
                    {
                        "time": int(row["time"]),
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row["tick_volume"]),
                    }
                )
            markers = timeframe_markers(
                filtered_rows,
                timeframe=timeframe,
                start_utc=start_utc,
                end_utc=now_utc,
                match_timeframe_only=timeframe in {"M1", "M5"},
            )
            result["timeframes"][timeframe] = {
                "label": timeframe,
                "candles": candles,
                "markers": markers,
                "windowHours": int(window.total_seconds() // 3600),
            }
        return result


def resolve_runtime_path(config_path: Path, raw_path: str) -> Path:
    target = Path(str(raw_path or "").strip())
    if target.is_absolute():
        return target
    return (REPO_ROOT / target).resolve()


def _json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class DashboardHandler(SimpleHTTPRequestHandler):
    state: DashboardState | None = None

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/snapshot":
            self._handle_snapshot(parsed.query)
            return

        target = STATIC_FILES.get(parsed.path)
        if target is None:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        file_path = DASHBOARD_DIR / target
        if not file_path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Missing dashboard file")
            return

        content_type = "text/html; charset=utf-8"
        if file_path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif file_path.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"

        payload = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _handle_snapshot(self, query: str) -> None:
        if self.state is None:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Dashboard state not initialized")
            return
        params = parse_qs(query)
        symbol = str(params.get("symbol", [self.state.symbols[0] if self.state.symbols else "EURUSD"])[0]).upper()
        try:
            payload = self.state.build_snapshot(symbol)
        except Exception as exc:
            data = _json_bytes({"error": str(exc)})
            self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        data = _json_bytes(payload)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    parser = ArgumentParser(description="Serve local trading dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--config", default=str(CONFIG_PATH), help="Path to bot config")
    parser.add_argument("--csv", default="", help="Optional explicit bot_events.csv path override")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    app_config = load_config(config_path)
    csv_path = resolve_runtime_path(config_path, args.csv or app_config.runtime.log_file)
    print(f"Dashboard config={config_path}")
    print(f"Dashboard log={csv_path}")

    state = DashboardState(config_path, csv_path)
    DashboardHandler.state = state
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Dashboard running on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        state.close()


if __name__ == "__main__":
    main()
