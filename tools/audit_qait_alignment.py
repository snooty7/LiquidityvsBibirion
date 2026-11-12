"""Audit alignment provenance and unchanged controls without importing trading code."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import subprocess

STEPS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}


def audit(before: Path, after: Path, output: Path) -> dict:
    """Verify frozen inputs, baseline/regime ledgers, exact anchors and causal breaks."""
    if output.exists():
        raise ValueError("Audit output already exists")
    control_ledgers = 0
    summaries = {}
    for scenario, protocol in (("base", "protocol.json"), ("doubled_costs", "stress_protocol.json")):
        old_protocol = json.loads((before/protocol).read_text(encoding="utf-8"))
        new_protocol = json.loads((after/protocol).read_text(encoding="utf-8"))
        for name in ("adaptive", "costs", "equity", "folds", "config_file_hash", "effective_config_hash", "history_file_hash"):
            assert old_protocol[name] == new_protocol[name], name
        assert not new_protocol["effective_config"]["adaptive"]["enabled"]
        original = json.loads((before/scenario/"report.json").read_text(encoding="utf-8"))
        corrected = json.loads((after/scenario/"report.json").read_text(encoding="utf-8"))
        lookup = {(row["fold"], row["phase"], row["arm"]): row for row in original["comparisons"]}
        observations = []
        tests = []
        for row in corrected["comparisons"]:
            if row["arm"] in {"baseline", "regime"}:
                assert row["trades"] == lookup[row["fold"], row["phase"], row["arm"]]["trades"]
                control_ledgers += 1
            if row["phase"] == "test":
                tests.append({key: row[key] for key in ("fold", "arm", "metrics")})
            if row["arm"] != "adaptive":
                continue
            for event in row["observations"]:
                anchor = event["anchor"]
                score = event["evaluation"]["score"]
                inputs = {item["name"]: item for item in score["observations"]}
                weights = new_protocol["adaptive"]["weights"]
                components = ("sweep", "structure", "zone", "regime", "order_flow")
                expected = sum(weight*(inputs[name]["value"] or 0) for name, weight in zip(components, weights))
                assert math.isclose(score["score"], expected, abs_tol=1e-12)
                assert inputs["order_flow"]["value"] is None
                if inputs["sweep"]["value"] is not None:
                    matches = [item for item in event["evaluation"]["structure"]["events"]
                               if item["kind"] == "SWEEP" and item["timeframe"] == anchor["signal_timeframe"]
                               and item["side"] == anchor["side"] and item["price"] == anchor["level"]
                               and item["available_at"] == anchor["candle_time"]+STEPS[anchor["signal_timeframe"]]]
                    assert matches
                if inputs["structure"]["value"] is not None:
                    matches = [item for item in event["evaluation"]["structure"]["events"]
                               if item["kind"] == "CONFIRMATION_BREAK" and item["side"] == anchor["side"]
                               and item["timeframe"] == anchor["confirmation_timeframe"]
                               and anchor["candle_time"]+STEPS[anchor["signal_timeframe"]] < item["available_at"] <= event["timestamp"]]
                    assert matches
                observations.append(event)
        summaries[scenario] = dict(
            observations=len(observations),
            verified_sweeps=sum(next(item for item in event["evaluation"]["score"]["observations"] if item["name"] == "sweep")["value"] is not None for event in observations),
            verified_confirmations=sum(next(item for item in event["evaluation"]["score"]["observations"] if item["name"] == "structure")["value"] is not None for event in observations),
            score_eligible=sum(not event["evaluation"]["score"]["reasons"] for event in observations),
            rejection_counts=dict(Counter(reason for event in observations for reason in event["reasons"])),
            test_results=tests, report_sha256=hashlib.sha256((after/scenario/"report.json").read_bytes()).hexdigest())
    unchanged = subprocess.run(["git", "diff", "--quiet", "1f4afdc", "--", "src/risk", "src/execution", "src/engine", "src/services/config.py", "src/strategy/adaptive/config.py", "config", "live"], capture_output=True)
    assert unchanged.returncode == 0, "Risk, execution, live configuration or adaptive thresholds changed"
    result = dict(status="passed", unchanged_control_ledgers=control_ledgers,
                  unchanged_settings="thresholds, weights, risk and regime settings, costs, folds, equity, original configuration and data",
                  risk_execution_configuration_diff="empty", scenarios=summaries,
                  note="Development-window diagnosis; no untouched holdout or profitability improvement claim")
    output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.before, args.after, args.output)
    print(json.dumps({"status": result["status"], "unchanged_control_ledgers": result["unchanged_control_ledgers"],
                      "diagnostics": {name: {key: values[key] for key in ("observations", "verified_sweeps", "verified_confirmations", "score_eligible", "rejection_counts")}
                                      for name, values in result["scenarios"].items()}}))
