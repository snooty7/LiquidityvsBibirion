"""Independent baseline level-lifecycle oracle; no trading implementation imports."""
import argparse
from bisect import bisect_right
from collections import Counter
import hashlib
import json
from pathlib import Path

STEPS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}


def _identity(row, event):
    anchor = event["anchor"]
    return (row["fold"], row["phase"], event["timestamp"], anchor["branch_id"],
            anchor["side"], anchor["level"], anchor["candle_time"])


def _source_map(bars, anchor):
    last = bars[-1]
    price = last["close"]
    source = [*bars, dict(time=last["time"]+STEPS[anchor["signal_timeframe"]], open=price, high=price, low=price, close=price)]
    pivots = []
    length = anchor["pivot_length"]
    for index in range(length, len(source)-length):
        window = source[index-length:index+length+1]
        if source[index]["high"] == max(bar["high"] for bar in window):
            pivots.append((index, source[index]["high"]))
        if source[index]["low"] == min(bar["low"] for bar in window):
            pivots.append((index, source[index]["low"]))
    pivots.sort(key=lambda item: item[0], reverse=True)
    levels = [price for _, price in pivots[:anchor["max_levels"]]]
    selected = None
    for level in levels:
        if last["high"] > level+anchor["buffer_price"] and last["close"] < level:
            selected = ("SELL", level)
            break
        if last["low"] < level-anchor["buffer_price"] and last["close"] > level:
            selected = ("BUY", level)
            break
    return levels, selected


def audit(history_path: Path, before: Path, after: Path, output: Path) -> dict:
    """Check restored source levels against raw history and unchanged ranking rules."""
    if output.exists():
        raise ValueError("Lifecycle audit output already exists")
    history = json.loads(history_path.read_text(encoding="utf-8-sig"))
    scenarios = {}
    for scenario in ("base", "doubled_costs"):
        old = json.loads((before/scenario/"report.json").read_text(encoding="utf-8"))
        new = json.loads((after/scenario/"report.json").read_text(encoding="utf-8"))
        formerly_rejected = {_identity(row, event) for row in old["comparisons"] if row["arm"] == "adaptive"
                             for event in row["observations"] if "anchor_liquidity_already_consumed" in event["reasons"]}
        verified, restored, prior_crossed = 0, 0, 0
        reasons, tests, train = Counter(), [], []
        for row in new["comparisons"]:
            if row["arm"] in {"scoring", "adaptive", "adaptive_shadow"}:
                record = dict(fold=row["fold"], arm=row["arm"], trades=row["metrics"]["trades"], net_pnl=row["metrics"]["net_pnl"])
                if row["phase"] == "test":
                    tests.append(record)
                elif row["phase"] == "train":
                    train.append(record)
            if row["arm"] != "adaptive":
                continue
            for event in row["observations"]:
                reasons.update(event["reasons"])
                value = next(item for item in event["evaluation"]["score"]["observations"] if item["name"] == "sweep")["value"]
                if value is None:
                    continue
                anchor = event["anchor"]
                symbol = anchor["branch_id"].split(":")[0]
                rows = history["symbols"][symbol]["rates"][anchor["signal_timeframe"]]
                times = [bar["time"] for bar in rows]
                end = bisect_right(times, anchor["candle_time"])
                source = rows[max(0, end-anchor["source_lookback"]):end]
                assert len(source) == anchor["source_lookback"] and source[-1]["time"] == anchor["candle_time"]
                levels, selected = _source_map(source, anchor)
                assert anchor["level"] in levels and selected == (anchor["side"], anchor["level"])
                sweep = next(item for item in reversed(event["evaluation"]["structure"]["events"])
                             if item["kind"] == "SWEEP" and item["available_at"] == anchor["candle_time"]+STEPS[anchor["signal_timeframe"]]
                             and item["price"] == anchor["level"] and item["side"] == anchor["side"])
                assert sweep["level_lifecycle"] == "baseline_ranked_rolling_pivots"
                pivot = next(index for index, bar in enumerate(source) if bar["time"] == sweep["pivot_time"])
                count = sum(bar["low"] < anchor["level"] if anchor["side"] == "BUY" else bar["high"] > anchor["level"]
                            for bar in source[pivot+anchor["pivot_length"]+1:-1])
                assert count == sweep["prior_crossings"]
                verified += 1
                prior_crossed += count > 0
                restored += _identity(row, event) in formerly_rejected
        assert reasons["anchor_liquidity_already_consumed"] == 0
        scenarios[scenario] = dict(verified_source_sweeps=verified, prior_crossed_but_active=prior_crossed,
                                    prior_false_consumed_rejections_restored=restored,
                                    rejection_counts=dict(reasons), training_results=train, test_results=tests)
    result = dict(status="passed", scenarios=scenarios,
                  auditor_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  contract="Ranked rolling source map at creation; no wick retirement; duplicate/execution guards separate",
                  limitation="Development-window eligibility audit, not an improvement or live-trading claim")
    output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.history, args.before, args.after, args.output)
    print(json.dumps(result))
