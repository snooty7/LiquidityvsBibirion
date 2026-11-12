"""Recompute volatility and HTF gates from raw candles without strategy imports."""
import argparse
from bisect import bisect_right
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from statistics import fmean, pstdev
import subprocess

STEPS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}


def _atr_rank(rows, period):
    ranges = [max(b["high"]-b["low"], abs(b["high"]-a["close"]), abs(b["low"]-a["close"]))
              for a, b in zip(rows, rows[1:])]
    current = fmean(ranges[:period])
    values = [current]
    for value in ranges[period:]:
        current = current+(value-current)/period
        values.append(current)
    prior = values[:-1]
    rank = sum(value < current and not math.isclose(value, current, rel_tol=1e-6) for value in prior)/len(prior)
    return current, rank, len(prior)


def _ema_direction(rows):
    previous = current = rows[0]["close"]
    for row in rows[1:]:
        previous = current
        current = 2/21*row["close"]+19/21*current
    price = rows[-1]["close"]
    direction = "BUY" if price > current and current >= previous else "SELL" if price < current and current <= previous else "UNCERTAIN"
    return dict(close=price, ema20=current, previous_ema20=previous, direction=direction)


def audit(history_path: Path, before: Path, after: Path, output: Path) -> dict:
    """Verify native cutoffs, volatility units, gate decisions and frozen inputs."""
    if output.exists():
        raise ValueError("Gate audit output already exists")
    history = json.loads(history_path.read_text(encoding="utf-8-sig"))["symbols"]
    indices = {(symbol, tf): [bar["time"] for bar in rows] for symbol, item in history.items()
               for tf, rows in item["rates"].items()}
    results = {}
    for scenario, protocol_name in (("base", "protocol.json"), ("doubled_costs", "stress_protocol.json")):
        prior_protocol = json.loads((before/protocol_name).read_text(encoding="utf-8"))
        protocol = json.loads((after/protocol_name).read_text(encoding="utf-8"))
        for key in ("adaptive", "costs", "equity", "folds", "config_file_hash", "effective_config_hash", "history_file_hash"):
            assert protocol[key] == prior_protocol[key], key
        assert not protocol["effective_config"]["adaptive"]["enabled"]
        config = protocol["adaptive"]
        old = json.loads((before/scenario/"report.json").read_text(encoding="utf-8"))
        new = json.loads((after/scenario/"report.json").read_text(encoding="utf-8"))
        old_rows = {(row["fold"], row["phase"], row["arm"]): row for row in old["comparisons"]}
        equal, changed, traces, causes = [], [], [], Counter()
        unique_boundaries = set()
        boundary_checks = 0
        for row in new["comparisons"]:
            key = (row["fold"], row["phase"], row["arm"])
            same = row["trades"] == old_rows[key]["trades"]
            (equal if same else changed).append(list(key))
            if row["arm"] == "baseline":
                assert same, "Legacy baseline changed"
            if row["arm"] != "adaptive":
                continue
            symbol = row["result"]["symbol"]
            data = history[symbol]["rates"]
            for event in row["observations"]:
                timestamp = event["timestamp"]
                entry_tf = config["entry_timeframe"]
                step = STEPS[entry_tf]
                end = bisect_right(indices[symbol, entry_tf], timestamp-step)
                used = data[entry_tf][max(0, end-config["lookback"]):end]
                reported = event["evaluation"]["regime"]
                trace = dict(fold=row["fold"], phase=row["phase"], decision_time=timestamp,
                             side=event["side"], regime=reported["regime"], timeframes={})
                if reported["reason"] == "insufficient_context":
                    assert reported["regime"] == "UNCERTAIN"
                    assert any("gapped" in reason or "insufficient" in reason or "stale" in reason
                               for reason in event["reasons"])
                    trace["volatility"] = dict(status="unavailable_data_blocked")
                    causes["unavailable_data"] += 1
                else:
                    assert len(used) == config["lookback"]
                    atr, rank, sample = _atr_rank(used, config["atr_period"])
                    returns = [math.log(b["close"]/a["close"]) for a, b in zip(used[-21:-1], used[-20:])]
                    realized = pstdev(returns)
                    assert math.isclose(atr, reported["atr"], abs_tol=1e-14, rel_tol=1e-12)
                    assert rank == reported["atr_percentile"]
                    assert math.isclose(realized, reported["realized_volatility"], abs_tol=1e-15, rel_tol=1e-12)
                    atr_block = rank >= config["high_atr_percentile"]
                    realized_block = realized >= config["high_realized_volatility"]
                    assert (reported["regime"] == "HIGH_VOLATILITY") == (atr > 0 and (atr_block or realized_block))
                    assert ("regime_block:HIGH_VOLATILITY" in event["reasons"]) == (reported["regime"] == "HIGH_VOLATILITY")
                    causes["atr_extreme"] += atr_block
                    causes["realized_extreme"] += realized_block
                    trace["volatility"] = dict(status="verified", atr=atr, prior_atr_samples=sample,
                                              percentile=rank, percentile_limit=config["high_atr_percentile"],
                                              realized_per_bar=realized, realized_limit=config["high_realized_volatility"],
                                              atr_block=atr_block, realized_block=realized_block,
                                              last_closed_at=used[-1]["time"]+step)
                expected_directions = []
                for tf in config["context_timeframes"]:
                    duration = STEPS[tf]
                    end = bisect_right(indices[symbol, tf], timestamp-duration)
                    bars = data[tf][max(0, end-config["lookback"]):end]
                    assert len(bars) == config["lookback"] and bars[-1]["time"]+duration <= timestamp
                    values = _ema_direction(bars)
                    expected_directions.append([tf, values["direction"]])
                    trace["timeframes"][tf] = values | dict(last_closed_at=bars[-1]["time"]+duration,
                                                           first_open_at=bars[0]["time"], bars=len(bars))
                    boundary = (symbol, tf, timestamp)
                    if boundary not in unique_boundaries:
                        close_time = bars[-1]["time"]+duration
                        minute_end = bisect_right(indices[symbol, "M1"], close_time-60)
                        minute = data["M1"][minute_end-1]
                        assert minute["time"] == close_time-60 and minute["close"] == bars[-1]["close"]
                        unique_boundaries.add(boundary)
                        boundary_checks += 1
                assert expected_directions == event["evaluation"]["directions"]
                opposition = any(direction in {"BUY", "SELL"} and direction != event["side"]
                                 for _, direction in expected_directions)
                assert ("timeframe_conflict" in event["reasons"]) == opposition
                causes["actual_timeframe_opposition"] += opposition
                for tf, direction in expected_directions:
                    if direction == "UNCERTAIN":
                        assert f"timeframe_uncertain:{tf}" in event["reasons"]
                traces.append(trace)
        results[scenario] = dict(identical_ledgers=len(equal), changed_ledgers=changed,
                                 gate_counts=dict(causes), native_htf_vs_m1_close_checks=boundary_checks,
                                 observation_count=len(traces), traces=traces)
    paths = ("src/risk", "src/execution", "src/engine", "src/services/config.py", "src/strategy/adaptive/config.py",
             "src/strategy/liquidity.py", "src/strategy/filters.py", "config", "live")
    diff = subprocess.run(["git", "diff", "--quiet", "8ec8dab", "--", *paths], capture_output=True)
    assert diff.returncode == 0, "Risk, baseline indicators, numerical settings or live execution changed"
    result = dict(status="passed", scenarios=results, settings_and_risk_unchanged=True,
                  auditor_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  limitation="Development-data gate verification; no profitability or untouched-holdout claim")
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
    print(json.dumps({"status": result["status"], "scenarios": {name: {key: values[key] for key in
          ("identical_ledgers", "changed_ledgers", "gate_counts", "native_htf_vs_m1_close_checks", "observation_count")}
          for name, values in result["scenarios"].items()}}))
