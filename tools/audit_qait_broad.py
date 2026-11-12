"""Audit fixed inputs, preregistered coverage and paired broad-study outputs."""
from collections import Counter
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import subprocess

from src.services.config import load_config
from src.tools.research_adaptive import source_digest, _config_hash
from tools.validate_qait_broad import ROOT, STUDY, digest, write_new


def audit():
    """Reject drift, incomplete arm pairs, overlapping tests or altered risk."""
    registration_path = STUDY / "registration.json"
    registration = json.loads(registration_path.read_text())
    assert registration["source_digest"] == source_digest(ROOT)
    assert registration["production_config_sha256"] == digest(ROOT / "config/settings.json")
    subprocess.run(["git", "diff", "--quiet", "8d1c4b6", "--", "src", "config", "live"], check=True)
    original = load_config(ROOT / "config/settings.json")
    assert not original.adaptive.enabled
    assert not original.adaptive.ml_shadow
    assert not original.adaptive.dynamic_leverage
    assert not original.adaptive.hedging
    reference = asdict(next(cfg for cfg in original.symbols if cfg.magic == 92001))
    prior = json.loads((ROOT / "reports/qait/scoring_92001/protocol.json").read_text())
    assert registration["source_digest"] == prior["source_digest"], "Prior signal implementation changed"
    records = []
    for job in registration["jobs"]:
        path = ROOT / job["protocol"]
        protocol = json.loads(path.read_text())
        assert digest(path) == job["protocol_sha256"]
        assert protocol["adaptive"] == prior["adaptive"], "Adaptive thresholds changed"
        app = load_config(Path(protocol["config"]))
        assert _config_hash(app) == protocol["effective_config_hash"]
        cfg = asdict(app.symbols[0])
        expected = dict(reference, symbol=job["symbol"])
        assert cfg == expected, "Signal/risk profile changed"
        assert not app.adaptive.enabled and app.runtime.dry_run
        assert not app.runtime.push_notifications_enabled
        for key, value in asdict(original.runtime).items():
            if key not in {"dry_run", "push_notifications_enabled", "push_notification_url", "push_notification_token"}:
                assert getattr(app.runtime, key) == value, key
        cost_key = "protocol.json" if job["scenario"] == "base" else "stress_protocol.json"
        old_costs = json.loads((ROOT / "reports/qait/scoring_92001" / cost_key).read_text())["costs"]
        assert protocol["costs"] == old_costs
        assert digest(Path(protocol["history"])) == protocol["history_file_hash"]
        tests = [(datetime.fromisoformat(fold["test_start"]), datetime.fromisoformat(fold["test_end"]))
                 for fold in protocol["folds"]]
        assert all(a[1] <= b[0] for a, b in zip(tests, tests[1:]))
        report_path = path.parent / job["scenario"] / "report.json"
        report = json.loads(report_path.read_text())
        assert report["protocol_hash"] == digest(path)
        assert report["source_digest"] == registration["source_digest"]
        assert report["data_role"] == protocol["data_role"]
        counts = Counter()
        pairs = {}
        rejections = Counter()
        for row in report["comparisons"]:
            key = (row["fold"], row["phase"])
            counts[key] += 1
            if row["status"] != "complete":
                assert row["status"] == "unavailable" and row["reason"]
                continue
            pairs.setdefault(key, {})[row["arm"]] = row["trades"]
            start, end = (datetime.fromisoformat(row[k]).timestamp() for k in ("start", "end"))
            assert all(start <= obs["timestamp"] <= end for obs in row["observations"])
            if row["phase"] == "test" and row["arm"] == "adaptive":
                for observation in row["observations"]:
                    rejections.update(observation["reasons"])
        assert len(counts) == 3 * len(protocol["folds"])
        assert all(n == (5 if key in pairs else 1) for key, n in counts.items())
        for arms in pairs.values():
            assert set(arms) == set(protocol["arms"])
            assert arms["adaptive"] == arms["adaptive_shadow"]
        records.append(dict(symbol=job["symbol"], scenario=job["scenario"],
                            report_sha256=digest(report_path), completed_phases=len(pairs),
                            unavailable_phases=len(counts)-len(pairs),
                            test_adaptive_reason_counts=dict(rejections.most_common())))
    output = STUDY / "contract_audit.json"
    write_new(output, dict(status="passed", registration_sha256=digest(registration_path),
                          auditor_sha256=digest(Path(__file__)), records=records,
                          checks=["source/config/history unchanged", "exact prior adaptive thresholds and costs",
                                  "matched signal/risk settings", "risk runtime preserved", "disabled defaults",
                                  "complete paired arms or explicit unavailable phase", "disjoint test windows",
                                  "observation timestamps within phase", "identical adaptive/shadow ledgers"]))
    print("Passed fixed-input and paired-output contract audit")


if __name__ == "__main__":
    audit()
