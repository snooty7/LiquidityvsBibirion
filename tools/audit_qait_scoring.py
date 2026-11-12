"""Independent normalization/score oracle using saved candles, not strategy imports."""
import argparse
from bisect import bisect_right
from collections import Counter
import json
import math
from pathlib import Path
from statistics import fmean
import subprocess

STEPS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}
NAMES = ("sweep", "structure", "zone", "regime", "order_flow")


def _atr(rows, period):
    ranges = [max(b["high"]-b["low"], abs(b["high"]-a["close"]), abs(b["low"]-a["close"]))
              for a, b in zip(rows, rows[1:])]
    value = fmean(ranges[:period])
    for item in ranges[period:]:
        value += (item-value)/period
    return value


def _identity(event):
    return (event["timestamp"], event["side"], event["anchor"]["candle_time"], event["anchor"]["level"])


def audit(history_path: Path, before: Path, after: Path, output: Path) -> dict:
    """Recompute price/ATR units, interval proximity, compatibility and fixed sums."""
    if output.exists():
        raise ValueError("Scoring audit output already exists")
    histories = json.loads(history_path.read_text(encoding="utf-8-sig"))["symbols"]
    indices = {(symbol, tf): [bar["time"] for bar in rows] for symbol, item in histories.items()
               for tf, rows in item["rates"].items()}
    results = {}
    for scenario, filename in (("base", "protocol.json"), ("doubled_costs", "stress_protocol.json")):
        prior = json.loads((before/filename).read_text(encoding="utf-8"))
        protocol = json.loads((after/filename).read_text(encoding="utf-8"))
        for key in ("adaptive", "costs", "equity", "folds", "config_file_hash", "effective_config_hash", "history_file_hash"):
            assert prior[key] == protocol[key], key
        assert not protocol["effective_config"]["adaptive"]["enabled"]
        config, costs = protocol["adaptive"], protocol["costs"]
        old = json.loads((before/scenario/"report.json").read_text(encoding="utf-8"))
        new = json.loads((after/scenario/"report.json").read_text(encoding="utf-8"))
        old_rows = {(row["fold"], row["phase"], row["arm"]): row for row in old["comparisons"]}
        counts, changes, paired, outcomes = Counter(), [], [], []
        for row in new["comparisons"]:
            key = (row["fold"], row["phase"], row["arm"])
            if row["arm"] in {"baseline", "regime"}:
                assert row["trades"] == old_rows[key]["trades"], "Unchanged control ledger drifted"
                counts["identical_control_ledgers"] += 1
            if row["trades"] != old_rows[key]["trades"]:
                changes.append(list(key))
            outcomes.append(dict(fold=row["fold"], phase=row["phase"], arm=row["arm"],
                                 trades=row["metrics"]["trades"], net_pnl=row["metrics"]["net_pnl"]))
            if row["arm"] not in {"baseline", "adaptive"}:
                continue
            symbol = row["result"]["symbol"]
            data, info = histories[symbol]["rates"], histories[symbol]["symbol_info"]
            pip = info["point"]*(10 if info["digits"] in (3, 5) else 1)
            old_lookup = {_identity(event): event for event in old_rows[key]["observations"]}
            for event in row["observations"]:
                timestamp, side, anchor = event["timestamp"], event["side"], event["anchor"]
                score = event["evaluation"]["score"]
                features = {item["name"]: item for item in score["observations"]}
                assert set(features) == set(NAMES)
                for name in ("sweep", "structure"):
                    feature = features[name]
                    if feature["value"] is None:
                        assert f"required_feature_unavailable:{name}" in score["reasons"]
                        continue
                    if name == "sweep":
                        matches = [item for item in event["evaluation"]["structure"]["events"]
                                   if item["kind"] == "SWEEP" and item["side"] == side and item["price"] == anchor["level"]
                                   and item["available_at"] == anchor["candle_time"]+STEPS[anchor["signal_timeframe"]]]
                    else:
                        matches = [item for item in event["evaluation"]["structure"]["events"] if item["kind"] == "CONFIRMATION_BREAK"]
                    observed = matches[-1]
                    tf = observed["timeframe"]
                    assert observed["available_at"] <= timestamp
                    end = bisect_right(indices[symbol, tf], observed["available_at"]-STEPS[tf])
                    rows = data[tf][end-config["lookback"]:end]
                    assert len(rows) == config["lookback"] and rows[-1]["time"]+STEPS[tf] == observed["available_at"]
                    atr = _atr(rows, config["atr_period"])
                    move = (anchor["level"]-rows[-1]["low"] if side == "BUY" else rows[-1]["high"]-anchor["level"]) if name == "sweep" else abs(rows[-1]["close"]-observed["price"])
                    expected = min(1, move/atr)
                    assert math.isclose(expected, feature["value"], rel_tol=1e-12, abs_tol=1e-12)
                    raw = dict(feature["raw"])
                    assert math.isclose(move, raw["move_price"], abs_tol=1e-12)
                    assert math.isclose(atr, raw["atr"], abs_tol=1e-14)
                    counts[f"verified_{name}_normalizations"] += 1
                regime = event["evaluation"]["regime"]
                state = regime["regime"]
                available = regime["reason"] not in {"insufficient_context", "invalid_context", "invalid_indicators", "zero_atr"}
                expected_regime = float(state == "RANGING" or state == "TRENDING_BULLISH" and side == "BUY" or state == "TRENDING_BEARISH" and side == "SELL") if available else None
                assert features["regime"]["value"] == expected_regime
                zones = [zone for zone in event["evaluation"]["structure"]["zones"] if zone["side"] == side and zone["status"] == "active"]
                if zones and regime["atr"] > 0:
                    minute_end = bisect_right(indices[symbol, "M1"], timestamp-60)
                    minute = data["M1"][minute_end-1]
                    spread = minute["spread"]*info["point"]/pip if costs["spread_mode"] == "historical" and "spread" in minute else costs["spread_pips"]
                    spread *= costs.get("spread_multiplier", 1)
                    quoted = minute["close"]+(spread*pip if side == "BUY" else 0)
                    fill = quoted+(costs["slippage_pips"]*pip if side == "BUY" else -costs["slippage_pips"]*pip)
                    distance = min(max(zone["low"]-fill, fill-zone["high"], 0) for zone in zones)
                    expected = max(0, 1-distance/regime["atr"]/2)
                    assert math.isclose(expected, features["zone"]["value"], rel_tol=1e-12, abs_tol=1e-12)
                    raw = dict(features["zone"]["raw"])
                    assert raw["scale_atr"] == 2 and math.isclose(raw["distance_price"], distance, abs_tol=1e-12)
                    counts["verified_zone_normalizations"] += 1
                else:
                    assert features["zone"]["value"] is None
                assert features["order_flow"]["value"] is None
                contributions = {name: weight*(features[name]["value"] or 0) for name, weight in zip(NAMES, config["weights"])}
                assert all(math.isclose(value, dict(score["contributions"])[name], abs_tol=1e-12) for name, value in contributions.items())
                expected_score = math.fsum(contributions.values())
                assert math.isclose(expected_score, score["score"], abs_tol=1e-12)
                assert expected_score <= 1-config["weights"][-1]+1e-12
                assert ("score_below_threshold" in score["reasons"]) == (expected_score+1e-12 < config["score_threshold"])
                counts["verified_scores"] += 1
                if row["arm"] == "baseline":
                    previous = old_lookup[_identity(event)]["evaluation"]["score"]
                    paired.append(dict(fold=row["fold"], phase=row["phase"], timestamp=timestamp,
                                       previous_score=previous["score"], corrected_score=score["score"],
                                       previous_reasons=previous["reasons"], corrected_reasons=score["reasons"]))
        results[scenario] = dict(checks=dict(counts), changed_ledgers=changes, paired_baseline_scores=paired, outcomes=outcomes)
    protected = ("src/risk", "src/execution", "src/engine", "src/services/config.py", "src/strategy/adaptive/config.py",
                 "src/strategy/liquidity.py", "src/strategy/filters.py", "config", "live")
    assert subprocess.run(["git", "diff", "--quiet", "d4ecf04", "--", *protected], capture_output=True).returncode == 0
    result = dict(status="passed", scenarios=results, unchanged_numeric_settings_and_risk=True,
                  limitation="Development-window feature audit, not an OOS performance improvement claim")
    output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.history, args.before, args.after, args.output)
    print(json.dumps({"status": report["status"], "scenarios": {name: {key: item[key] for key in ("checks", "changed_ledgers")}
          for name, item in report["scenarios"].items()}}))
