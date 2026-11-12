"""Record instrument-specific saved-bar evidence around the disputed closure."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEFORE = ROOT / "reports/qait/broad_20261112"
OUTPUT = ROOT / "reports/qait/gaps_20261112/holiday_scope.json"


def audit():
    """Count raw bars without assigning any absent minute a market schedule."""
    start = int(datetime(2026, 4, 3, tzinfo=timezone.utc).timestamp())
    records = []
    for symbol in ("EURUSD", "GBPUSD", "USDCHF", "NZDUSD"):
        protocol = json.loads((BEFORE/symbol/"base_protocol.json").read_text())
        raw = Path(protocol["history"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == protocol["history_file_hash"]
        rates = json.loads(raw)["symbols"][symbol]["rates"]
        counts = {tf: sum(start <= bar["time"] < start+86400 for bar in bars)
                  for tf, bars in rates.items()}
        samples = {tf: next((bar for bar in rates.get(tf,()) if start <= bar["time"] < start+86400), None)
                   for tf in ("H1", "H4")}
        records.append(dict(symbol=symbol, history_sha256=protocol["history_file_hash"],
                            native_bar_counts=counts, native_samples=samples))
        del raw, rates
    with OUTPUT.open("x",encoding="utf-8") as stream:
        json.dump(dict(date_utc="2026-04-03", records=records,
                       auditor_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       conclusion="Saved observations differ by instrument. No cross-instrument holiday closure or tradable-price substitution can be inferred; broker schedules remain unavailable."),stream,indent=2)
    print("Recorded cross-instrument native bar evidence without inferring closures")


if __name__ == "__main__":
    audit()
