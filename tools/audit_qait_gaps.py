"""Audit frozen gap decisions against independent raw timestamp arithmetic.

No inferred holiday/session calendar, price filling, broker connection or change
to the frozen experiment is permitted. Repeats keep original protocol bytes.
"""
from bisect import bisect_right
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parents[1]
BEFORE = ROOT / "reports/qait/broad_20261112"
OUTPUT = ROOT / "reports/qait/gaps_20261112"
STEPS = dict(M1=60, M5=300, M15=900, M30=1800, H1=3600, H4=14400, D1=86400)
GAP_ERRORS = {"gapped_or_unordered", "stale_bars", "insufficient_bars"}


def digest(path):
    """Hash exact bytes in bounded memory."""
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            value.update(block)
    return value.hexdigest()


def write_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)


def weekday(timestamp):
    """UTC weekday using integer epoch days, independent of production datetime."""
    return (timestamp // 86400 + 3) % 7


def separation(before, after, step):
    """Enumerate absent aligned bar opens, without inferring tradable prices."""
    missing = range(before+step, after, step)
    count = len(missing)
    weekday_missing = sum(weekday(t) < 5 for t in missing)
    return dict(previous_open=before, next_open=after, separation_seconds=after-before,
                missing_opens=count, missing_weekday_opens=weekday_missing,
                weekend_only=count > 0 and weekday_missing == 0)


def derived_times(m1, step):
    """Independently require every constituent minute before admitting a bucket."""
    buckets = {}
    for timestamp in m1:
        buckets.setdefault(timestamp//step*step, []).append(timestamp)
    return [start for start, times in sorted(buckets.items())
            if len(times) == step//60 and times == list(range(start, start+step, 60))]


def expected_error(times, step, decision, count, config):
    """Oracle for the explicitly frozen calendar, window and wall-clock contract."""
    end = bisect_right(times, decision-step)
    selected = times[max(0, end-count):end]
    # Extra level provenance does not enlarge the fixed indicator gap window.
    feature_window = selected[-config["lookback"]:]
    for before, after in zip(feature_window, feature_window[1:]):
        if after-before == step:
            continue
        gap = separation(before, after, step)
        permitted = (config["allow_utc_weekend_gaps"] and after-before <= 3*86400
                     and gap["weekend_only"])
        if not permitted:
            return "gapped_or_unordered"
    if len(selected) < count:
        return "insufficient_bars"
    if decision-selected[-1]-step > config["max_age_bars"]*step:
        return "stale_bars"
    return None


def audit():
    """Check all recorded feature/proof context rejections, not a favorable sample."""
    OUTPUT.mkdir(exist_ok=False)
    registration = json.loads((BEFORE / "registration.json").read_text())
    records = []
    for symbol in ("EURUSD", "GBPUSD", "USDCHF", "NZDUSD"):
        protocol = json.loads((BEFORE / symbol / "base_protocol.json").read_text())
        history_path = Path(protocol["history"])
        assert digest(history_path) == protocol["history_file_hash"]
        data = json.loads(history_path.read_bytes())["symbols"][symbol]["rates"]
        times = {tf: [row["time"] for row in rows] for tf, rows in data.items()}
        del data
        config = protocol["adaptive"]
        cfg = protocol["effective_config"]["symbols"][0]
        required = tuple(dict.fromkeys((config["entry_timeframe"], *config["context_timeframes"], "M1")))
        frames = []
        for tf in required:
            native = tf in times
            if not native:
                times[tf] = derived_times(times["M1"], STEPS[tf])
            gaps = [separation(a,b,STEPS[tf]) for a,b in zip(times[tf],times[tf][1:]) if b-a != STEPS[tf]]
            categories = Counter("weekend_only" if g["weekend_only"] else "contains_weekday" for g in gaps)
            examples = {}
            for gap in gaps:
                category = "weekend_only" if gap["weekend_only"] else "contains_weekday"
                if len(examples.setdefault(category, [])) < 3:
                    examples[category].append(gap)
            frames.append(dict(timeframe=tf, native=native, bars=len(times[tf]),
                               gap_categories=dict(categories), examples=examples))
        checked = Counter()
        rejected = Counter()
        oracle_cache = {}
        discrepancies = []
        for scenario in ("base", "doubled_costs"):
            archive = BEFORE / symbol / scenario / "report.json.gz"
            with gzip.open(archive, "rt", encoding="utf-8") as stream:
                report = json.load(stream)
            for row in report["comparisons"]:
                if row["status"] != "complete":
                    continue
                for observation in row["observations"]:
                    decision = observation["timestamp"]
                    anchor = observation["anchor"]
                    lookbacks = {}
                    if anchor is not None:
                        elapsed = max(0, decision-anchor["candle_time"]-STEPS[anchor["signal_timeframe"]])
                        source_step = STEPS[anchor["signal_timeframe"]]
                        lower_step = STEPS[anchor["confirmation_timeframe"]]
                        lookbacks[anchor["signal_timeframe"]] = max(config["lookback"], anchor["source_lookback"])+(elapsed+source_step-1)//source_step
                        lookbacks[anchor["confirmation_timeframe"]] = max(lookbacks.get(anchor["confirmation_timeframe"],0), config["lookback"]+(elapsed+lower_step-1)//lower_step, cfg["cisd_lookback_bars"])
                    expected = set()
                    for proof in (False, True) if anchor else (False,):
                        for tf in required if proof else required[:-1]:
                            count = lookbacks.get(tf, config["lookback"]) if proof else config["lookback"]
                            key = (tf, decision, count)
                            if key not in oracle_cache:
                                oracle_cache[key] = expected_error(times[tf], STEPS[tf], decision, count, config)
                            error = oracle_cache[key]
                            if error:
                                expected.add(f"{tf}:{error}")
                    recorded = {reason for reason in observation["evaluation"]["reasons"]
                                if ":" in reason and reason.split(":",1)[1] in GAP_ERRORS}
                    checked[scenario] += 1
                    rejected.update(recorded)
                    if recorded != expected:
                        discrepancies.append(dict(scenario=scenario, fold=row["fold"], phase=row["phase"],
                                                  arm=row["arm"], timestamp=decision,
                                                  recorded=sorted(recorded), expected=sorted(expected)))
        records.append(dict(symbol=symbol, history_sha256=protocol["history_file_hash"],
                            frames=frames, checked_observations=dict(checked),
                            oracle_windows=len(oracle_cache), rejection_counts=dict(rejected),
                            discrepancies=discrepancies))
        print(f"{symbol}: {sum(checked.values())} observations, {len(discrepancies)} discrepancies", flush=True)
    write_new(OUTPUT / "gap_audit.json", dict(
        status="passed" if not any(r["discrepancies"] for r in records) else "discrepancies_found",
        auditor_sha256=digest(Path(__file__)), original_registration_sha256=digest(BEFORE/"registration.json"),
        records=records,
        contract="Explicit UTC weekend missing opens only; weekday/holiday gaps remain unavailable; fixed three-day calendar separation and wall-clock freshness unchanged",
        limitation="Agreement with the frozen contract is not evidence of broker session/holiday schedules. None are present in these exports. No holiday or rollover closure is inferred from absence of prices."))


def register_repeat():
    """Freeze all repeat jobs using original protocols, source and inputs."""
    from src.tools.research_adaptive import source_digest
    original = json.loads((BEFORE / "registration.json").read_text())
    assert source_digest(ROOT) == original["source_digest"]
    assert json.loads((OUTPUT / "gap_audit.json").read_text())["status"] == "passed"
    write_new(OUTPUT / "repeat_registration.json", dict(
        status="frozen_before_replay", registered_at_utc=datetime.now(timezone.utc).isoformat(),
        source_digest=source_digest(ROOT), orchestrator_sha256=digest(Path(__file__)),
        original_registration_sha256=digest(BEFORE/"registration.json"), jobs=original["jobs"],
        expectation="No demonstrated contract bug: unchanged source, inputs, thresholds, risk and original protocol bytes; all eight complete reports must reproduce byte for byte",
        safety="Broker operations forbidden; adaptive defaults remain false; offline history only"))


def run(symbol, scenario):
    """Run an original frozen protocol into a fresh output, with a broker tripwire."""
    from src.tools.research_adaptive import source_digest, run_protocol
    registration = json.loads((OUTPUT / "repeat_registration.json").read_text())
    assert digest(Path(__file__)) == registration["orchestrator_sha256"]
    assert source_digest(ROOT) == registration["source_digest"]
    for job in registration["jobs"]:
        assert digest(ROOT/job["protocol"]) == job["protocol_sha256"]
    job = next(j for j in registration["jobs"] if j["symbol"]==symbol and j["scenario"]==scenario)
    from src.execution.mt5_adapter import MT5Adapter
    def forbidden(*args, **kwargs):
        raise AssertionError("Broker access forbidden in gap audit replay")
    for name in vars(MT5Adapter):
        if name != "pip_size" and not name.startswith("__") and callable(getattr(MT5Adapter,name)):
            setattr(MT5Adapter,name,forbidden)
    run_protocol(ROOT/job["protocol"], OUTPUT/symbol/scenario)


def verify():
    """Require exact equality of all reports; retain pointers to original archives."""
    registration = json.loads((OUTPUT / "repeat_registration.json").read_text())
    artifacts = json.loads((BEFORE/"artifact_manifest.json").read_text())
    records = []
    for job in registration["jobs"]:
        raw = OUTPUT/job["symbol"]/job["scenario"]/"report.json"
        original = next(r for r in artifacts["reports"] if r["raw"] == str((BEFORE/job["symbol"]/job["scenario"]/"report.json").relative_to(ROOT)).replace("\\","/"))
        assert digest(raw) == original["raw_sha256"]
        assert raw.stat().st_size == original["raw_bytes"]
        records.append(dict(symbol=job["symbol"], scenario=job["scenario"],
                            repeated_report_sha256=digest(raw), bytes=raw.stat().st_size,
                            original_archive=original["packed"], original_archive_sha256=original["packed_sha256"]))
    write_new(OUTPUT/"repeat_verification.json",dict(status="passed", records=records,
              repeat_registration_sha256=digest(OUTPUT/"repeat_registration.json"),
              result="All eight reports reproduced byte for byte; unchanged full ledgers and unavailable phases; identical archived originals retained without redundant copies"))
    print("All eight frozen reports reproduced byte for byte")


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("audit","register-repeat","run","verify"))
    parser.add_argument("--symbol")
    parser.add_argument("--scenario")
    args=parser.parse_args()
    if args.command=="audit": audit()
    elif args.command=="register-repeat": register_repeat()
    elif args.command=="verify": verify()
    else: run(args.symbol,args.scenario)
