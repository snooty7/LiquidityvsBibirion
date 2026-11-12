"""Independent raw-timestamp audit of broad-study coverage rejections."""
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "reports/qait/broad_20261112"


def utc(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def audit():
    """Record actual bar separations without filling or redefining market hours."""
    records = []
    for symbol in ("EURUSD", "GBPUSD", "USDCHF", "NZDUSD"):
        protocol = json.loads((STUDY / symbol / "base_protocol.json").read_text())
        path = Path(protocol["history"])
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == protocol["history_file_hash"]
        document = json.loads(raw)
        times = [bar["time"] for bar in document["symbols"][symbol]["rates"]["M1"]]
        del document, raw
        windows = []
        for fold in protocol["folds"]:
            start = datetime.fromisoformat(fold["train_start"])
            fit_end = start + timedelta(days=protocol["train_days"])
            validation_start = fit_end + timedelta(days=protocol["embargo_days"])
            phases = [("train", start, fit_end),
                      ("validation", validation_start, datetime.fromisoformat(fold["train_end"])),
                      ("test", datetime.fromisoformat(fold["test_start"]), datetime.fromisoformat(fold["test_end"]))]
            for phase, start, end in phases:
                left, right = int(start.timestamp()), int(end.timestamp())
                relevant = times[bisect_left(times, left):bisect_left(times, right)]
                boundaries = [left, *relevant, right]
                gaps = [dict(previous_boundary_utc=utc(a), next_boundary_utc=utc(b),
                             separation_seconds=b-a, separation_hours=(b-a)/3600)
                        for a, b in zip(boundaries, boundaries[1:]) if b-a > 3*86400]
                windows.append(dict(fold=fold["index"], phase=phase, start=start.isoformat(),
                                    end=end.isoformat(), m1_bars=len(relevant), gaps_over_fixed_limit=gaps))
        records.append(dict(symbol=symbol, history_sha256=protocol["history_file_hash"],
                            first_m1_utc=utc(times[0]), last_m1_utc=utc(times[-1]),
                            m1_bars=len(times), windows=windows))
    output = STUDY / "coverage_audit.json"
    with output.open("x", encoding="utf-8") as stream:
        json.dump(dict(status="complete", fixed_max_gap_days=3, records=records,
                       auditor_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       interpretation="Calendar bar separations, including holidays/closures; not proof of missing tradable prices. Existing fixed coverage rule retained without exceptions."), stream, indent=2)
    print("Recorded raw timestamp coverage for all registered phases")


if __name__ == "__main__":
    audit()
