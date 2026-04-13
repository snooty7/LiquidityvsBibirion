from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import json
import shutil
import sys

DASHBOARD_DIR = Path(__file__).resolve().parent
REPO_ROOT = DASHBOARD_DIR.parents[0]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard.server import CONFIG_PATH, DashboardState, resolve_runtime_path


ONLINE_CONFIG_SNIPPET = """  <script>
    window.DASHBOARD_CONFIG = {
      snapshotMode: "static",
      dataBasePath: "data"
    };
  </script>
"""


def build_static_dashboard(output_dir: Path, config_path: Path, csv_path: Path | None = None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    for filename in ("styles.css", "app.js"):
        shutil.copy2(DASHBOARD_DIR / filename, output_dir / filename)

    index_html = (DASHBOARD_DIR / "index.html").read_text(encoding="utf-8")
    if "</head>" not in index_html:
        raise RuntimeError("Dashboard index.html is missing </head>.")
    rendered_index = index_html.replace("</head>", ONLINE_CONFIG_SNIPPET + "</head>", 1)
    (output_dir / "index.html").write_text(rendered_index, encoding="utf-8")

    app_csv_path = csv_path
    if app_csv_path is None:
        from src.services.config import load_config

        app_config = load_config(config_path)
        app_csv_path = resolve_runtime_path(config_path, app_config.runtime.log_file)

    state = DashboardState(config_path, app_csv_path)
    try:
        manifest = {
            "symbols": state.symbols,
            "defaultSymbol": state.symbols[0] if state.symbols else "EURUSD",
        }
        for symbol in state.symbols:
            snapshot = state.build_snapshot(symbol)
            manifest["generated_at_utc"] = snapshot["generated_at_utc"]
            target = data_dir / f"snapshot-{symbol.upper()}.json"
            target.write_text(
                json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )

        (data_dir / "index.json").write_text(
            json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    finally:
        state.close()


def main() -> None:
    parser = ArgumentParser(description="Export dashboard as static site with pre-generated snapshots")
    parser.add_argument(
        "--output-dir",
        default=str(DASHBOARD_DIR / "online_build"),
        help="Output directory for generated static dashboard",
    )
    parser.add_argument("--config", default=str(CONFIG_PATH), help="Path to bot config")
    parser.add_argument("--csv", default="", help="Optional explicit bot_events.csv path override")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    csv_path = resolve_runtime_path(config_path, args.csv) if args.csv else None
    build_static_dashboard(Path(args.output_dir).resolve(), config_path, csv_path)
    print(f"Static dashboard exported to {Path(args.output_dir).resolve()}")


if __name__ == "__main__":
    main()
