"""Preregister and replay a fixed, offline multi-instrument development study.

This orchestrates the existing frozen runner. It never contacts a broker and
does not change the signal, risk model, thresholds, or production configuration.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from src.backtesting.costs import ExecutionCosts
from src.services.config import load_config
from src.tools.research_adaptive import freeze, run_protocol, source_digest


ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "reports/qait/broad_20261112"
UNIVERSE = {
    "EURUSD": ("EURUSD_extended.json", "2024-11-01"),
    "GBPUSD": ("GBPUSD_extended.json", "2024-11-01"),
    "USDCHF": ("USDCHF_extended.json", "2024-11-01"),
    "NZDUSD": ("NZDUSD.json", "2025-08-15"),
}
SCENARIOS = {"base": ExecutionCosts(), "doubled_costs": ExecutionCosts(
    spread_multiplier=2, commission_per_lot=7, slippage_pips=.4)}


def digest(path):
    """Fingerprint exact bytes without loading large history files at once."""
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_new(path, value):
    """Never replace preregistration or completed evidence."""
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False))


def register():
    """Freeze the entire universe and both cost scenarios before any replay."""
    if STUDY.exists():
        raise ValueError("Study directory already exists; do not revise a registered experiment")
    app = load_config(ROOT / "config/settings.json")
    template = next(cfg for cfg in app.symbols if cfg.magic == 92001)
    assert not app.adaptive.enabled and not template.ignore_portfolio_cap
    STUDY.mkdir(parents=True)
    jobs = []
    for symbol, (filename, start) in UNIVERSE.items():
        directory = STUDY / symbol
        directory.mkdir()
        # Matched research branches: only instrument changes. All signal and
        # risk fields remain identical to the established EURUSD 92001 branch.
        cfg = asdict(template)
        cfg["symbol"] = symbol
        runtime = asdict(app.runtime)
        runtime.update(dry_run=True, push_notifications_enabled=False,
                       push_notification_url="", push_notification_token="")
        config = directory / "offline_config.json"
        write_new(config, dict(runtime=runtime, symbols=[cfg], adaptive=asdict(app.adaptive)))
        loaded = load_config(config)
        assert asdict(loaded.symbols[0]) == cfg
        for key, value in asdict(app.runtime).items():
            if key not in {"dry_run", "push_notifications_enabled", "push_notification_url", "push_notification_token"}:
                assert getattr(loaded.runtime, key) == value, key
        for scenario, costs in SCENARIOS.items():
            protocol = directory / f"{scenario}_protocol.json"
            freeze(config=config, history=ROOT / "history/mt5_20261111" / filename,
                   magic=template.magic, start=start, end="2026-11-11", output=protocol,
                   train_days=90, validation_days=30, test_days=180,
                   embargo_days=1, equity=10000, costs=costs)
            jobs.append(dict(symbol=symbol, scenario=scenario,
                             protocol=str(protocol.relative_to(ROOT)), protocol_sha256=digest(protocol)))
    write_new(STUDY / "registration.json", dict(
        status="preregistered_before_all_replays", registered_at_utc=datetime.now(timezone.utc).isoformat(),
        source_digest=source_digest(ROOT), orchestration_sha256=digest(Path(__file__)),
        production_config_sha256=digest(ROOT / "config/settings.json"),
        universe=UNIVERSE, jobs=jobs,
        branch_contract="EURUSD 92001 M5/M1 profile cloned across four FX instruments; only symbol changes; isolated accounts, never portfolio returns",
        windows="90 calendar days train, 1 embargo, 30 validation, 1 embargo, 180 test; rolling, nonoverlapping tests; discard incomplete terminal fold",
        parameters="No fitting, threshold changes, risk changes, symbol selection, or outcome-dependent reruns",
        data_role="Previously researched development exports, including earlier strategies; chronological test windows are NOT untouched holdouts",
        provenance=["reports/fx_htf/plan.json", "reports/walk_forward/report.json",
                    "reports/qait/scoring_92001/protocol.json", "history/mt5_20261111/manifest.json",
                    "history/mt5_20261111/FX_extended_manifest.json", "history/mt5_20261111/USDCHF_extended_manifest.json"],
        untouched_holdout="None verifiably available in saved exports. Future data after 2026-11-11 requires separate prospective registration, without changes selected from these results.",
        endpoints=["test closed-position count", "net P&L after costs", "profit factor", "mean R", "maximum realized drawdown", "regime and session participation", "shadow ledger identity"],
        inference="Descriptive paired arm comparisons only; no pooled multi-symbol portfolio, no independent-sample claim for overlapping training phases; no live-profitability or confirmatory significance claim",
        coverage="Existing strict coverage and gap checks remain authoritative; unavailable windows reported, never filled or relaxed",
        safety="Offline saved candles only; adapter access forbidden in worker; adaptive, ML, leverage and hedge defaults remain disabled; no live trades"))
    print(f"Registered {len(jobs)} jobs: {STUDY}", flush=True)


def run(symbol, scenario):
    """Verify registration and forbid all adapter operations before replay."""
    registration = json.loads((STUDY / "registration.json").read_text())
    amendment_path = STUDY / "harness_amendment.json"
    if amendment_path.exists():
        amendment = json.loads(amendment_path.read_text())
        assert amendment["registration_sha256"] == digest(STUDY / "registration.json")
        assert amendment["orchestration_sha256"] == digest(Path(__file__))
    else:
        assert registration["orchestration_sha256"] == digest(Path(__file__))
    assert registration["source_digest"] == source_digest(ROOT)
    assert registration["production_config_sha256"] == digest(ROOT / "config/settings.json")
    for job in registration["jobs"]:
        assert digest(ROOT / job["protocol"]) == job["protocol_sha256"]
    job = next(job for job in registration["jobs"] if job["symbol"] == symbol and job["scenario"] == scenario)
    from src.execution.mt5_adapter import MT5Adapter
    def forbidden(*args, **kwargs):
        raise AssertionError("Broker access is forbidden in this offline study")
    # Fail closed even if a later replay regression accidentally reaches an adapter.
    for name in list(vars(MT5Adapter)):
        if name != "pip_size" and not name.startswith("__") and callable(getattr(MT5Adapter, name)):
            setattr(MT5Adapter, name, forbidden)
    run_protocol(ROOT / job["protocol"], STUDY / symbol / scenario)


def summarize():
    """Audit completed ledgers and tabulate paired tests without pooling accounts."""
    from tools.audit_qait_results import audit
    registration = json.loads((STUDY / "registration.json").read_text())
    records = []
    for symbol, (filename, _) in UNIVERSE.items():
        reports = [STUDY / symbol / scenario / "report.json" for scenario in SCENARIOS]
        audit(ROOT / "history/mt5_20261111" / filename, reports, STUDY / symbol / "money_audit.json")
        for scenario, path in zip(SCENARIOS, reports):
            report = json.loads(path.read_text())
            assert report["source_digest"] == registration["source_digest"]
            for row in report["comparisons"]:
                if row["status"] != "complete":
                    records.append(dict(symbol=symbol, scenario=scenario, **row))
                    continue
                records.append(dict(symbol=symbol, scenario=scenario, fold=row["fold"],
                                    phase=row["phase"], arm=row["arm"], start=row["start"], end=row["end"],
                                    status=row["status"], metrics=row["metrics"],
                                    observations=len(row["observations"])))
    write_new(STUDY / "summary.json", dict(
        status="complete", registration_sha256=digest(STUDY / "registration.json"),
        records=records, improvement_claim=False,
        limitation="All results are descriptive development evidence; isolated accounts are not a synchronized portfolio; no untouched holdout available"))
    print(f"Summarized {len(records)} comparisons", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("register", "run", "summarize"))
    parser.add_argument("--symbol", choices=UNIVERSE)
    parser.add_argument("--scenario", choices=SCENARIOS)
    args = parser.parse_args()
    if args.command == "register":
        register()
    elif args.command == "run":
        if not args.symbol or not args.scenario:
            parser.error("run requires --symbol and --scenario")
        run(args.symbol, args.scenario)
    else:
        summarize()


if __name__ == "__main__":
    main()
