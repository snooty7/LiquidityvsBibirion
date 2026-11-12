"""Freeze and run an offline five-arm adaptive study. Never connects to MT5."""
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from src.backtesting.adaptive import AdaptiveReplayPolicy, ARMS
from src.backtesting.adaptive_metrics import ledger_metrics
from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import load_history
from src.services.config import load_config
from src.strategy.adaptive.config import load_adaptive
from src.tools.backtest_mt5 import run_backtest
from src.tools.walk_forward import history_coverage, make_folds


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_digest(root: Path) -> str:
    """Hash Python source and dashboard inputs, including uncommitted implementation."""
    paths = sorted([*(root/"src").rglob("*.py"), *(root/"dashboard").glob("*.py"),
                    *(root/"dashboard").glob("*.js"), *(root/"dashboard").glob("*.html")])
    payload = [(str(path.relative_to(root)).replace("\\", "/"),
                hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest()) for path in paths]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _finite_json(value):
    """Represent undefined ratios as null rather than emitting nonstandard JSON."""
    import math
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _finite_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_json(item) for item in value]
    return value


def _config_hash(app) -> str:
    return hashlib.sha256(json.dumps(asdict(app), sort_keys=True, allow_nan=False).encode()).hexdigest()


def _public_config(app) -> dict:
    result = asdict(app)
    for name in ("push_notification_url", "push_notification_token"):
        result["runtime"][name] = "<redacted>" if result["runtime"].get(name) else ""
    return result


def freeze(*, config: Path, history: Path, magic: int, start: str, end: str,
           output: Path, train_days: int, validation_days: int, test_days: int,
           embargo_days: int, equity: float, costs: ExecutionCosts) -> Path:
    """Write a reviewable protocol before any replay; never overwrite an experiment."""
    if output.exists():
        raise ValueError("Protocol output must not already exist")
    if min(train_days, validation_days, test_days, equity) <= 0 or embargo_days < 0:
        raise ValueError("Invalid fold/equity settings")
    app = load_config(config)
    selected = [item for item in app.symbols if item.magic == magic]
    if len(selected) != 1 or selected[0].ignore_portfolio_cap:
        raise ValueError("Select exactly one branch without a portfolio bypass")
    # Explicit research override, never write to settings.json or enable live flow.
    adaptive = replace(app.adaptive, enabled=True, entry_timeframe=selected[0].timeframe,
                       allow_utc_weekend_gaps=True)
    folds = make_folds(_time(start), _time(end), train_days+validation_days+embargo_days,
                       test_days, embargo_days)
    root = Path(__file__).resolve().parents[2]
    protocol = dict(schema_version=1, status="frozen_before_replay", magic=magic,
                    config=str(config.resolve()), config_file_hash=_hash(config),
                    effective_config=_public_config(app), effective_config_hash=_config_hash(app),
                    history=str(history.resolve()),
                    history_file_hash=_hash(history), source_digest=source_digest(root),
                    adaptive=asdict(adaptive), costs=asdict(costs), equity=equity,
                    start=_time(start).isoformat(), end=_time(end).isoformat(),
                    train_days=train_days, validation_days=validation_days,
                    embargo_days=embargo_days, test_days=test_days,
                    folds=[fold.record() for fold in folds], arms=ARMS,
                    data_role="previously_researched_development_history_not_untouched_holdout",
                    selection="fixed preregistered parameters; no optimization using validation or OOS",
                    portfolio="one isolated branch, reset per phase/fold; not a synchronized multi-symbol account")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(protocol, indent=2, allow_nan=False), encoding="utf-8")
    return output


def run_protocol(path: Path, output: Path) -> dict:
    """Verify frozen inputs and replay chronologically with identical shadow ledgers."""
    protocol = json.loads(path.read_text(encoding="utf-8"))
    root = Path(__file__).resolve().parents[2]
    if source_digest(root) != protocol["source_digest"]:
        raise ValueError("Implementation changed since protocol freeze")
    config_path, history_path = Path(protocol["config"]), Path(protocol["history"])
    if _hash(config_path) != protocol["config_file_hash"] or _hash(history_path) != protocol["history_file_hash"]:
        raise ValueError("Frozen source data/configuration changed")
    app = load_config(config_path)
    # Includes .local override resolution: frozen effective config must match too.
    if _config_hash(app) != protocol["effective_config_hash"]:
        raise ValueError("Effective configuration changed, including local overrides")
    cfg = next(item for item in app.symbols if item.magic == protocol["magic"])
    history = load_history(history_path)[cfg.symbol]
    adaptive = load_adaptive(protocol["adaptive"])
    costs = ExecutionCosts(**protocol["costs"])
    output.mkdir(parents=True, exist_ok=False)
    report = dict(protocol_hash=_hash(path), source_digest=protocol["source_digest"],
                  history_digest=history.digest(), data_role=protocol["data_role"],
                  status="complete", comparisons=[], limitations=[
                      "Development historical comparison, not an untouched holdout or evidence of live profitability.",
                      "One independent branch per fold/phase; no synchronized multi-instrument portfolio simulation.",
                      "Full adaptive arm modifies eligible baseline candidates; it does not generate an independent entry stream.",
                      "No tick path, financing, historical margin/stop constraints, dynamic valuation or marked-equity curve.",
                      "ML model unavailable: shadow observer logs explicit unavailability; no LightGBM/XGBoost dependency installed.",
                      "Partial exits are offline only; broker milestone persistence/activation is not enabled.",
                      "Fixed thresholds, no fitted optimization or improvement claim; strict gap checks may hold cash."])
    checked_ledgers = 0
    for index, fold in enumerate(protocol["folds"], 1):
        # Fold records use ISO values emitted by the existing fold contract.
        train_start, train_end = _time(fold["train_start"]), _time(fold["train_end"])
        test_start, test_end = _time(fold["test_start"]), _time(fold["test_end"])
        fit_end = train_start + timedelta(days=protocol["train_days"])
        validation_start = fit_end + timedelta(days=protocol["embargo_days"])
        phases = (("train", train_start, fit_end), ("validation", validation_start, train_end),
                  ("test", test_start, test_end))
        for phase, start, end in phases:
            coverage = history_coverage(history, cfg, start, end)
            if coverage:
                report["status"] = "partial_or_unavailable"
                report["comparisons"].append(dict(fold=index, phase=phase, status="unavailable", reason=coverage))
                continue
            ledgers = {}
            for arm in ARMS:
                policy = AdaptiveReplayPolicy(history, adaptive, arm)
                result, trades = run_backtest(app, cfg, start, end, initial_equity=protocol["equity"],
                                             costs=costs, history=history, end_exclusive=True,
                                             entry_policy=policy.entry,
                                             exit_policy=policy.exit if arm in {"adaptive", "adaptive_shadow"} else None)
                ledgers[arm] = [asdict(trade) for trade in trades]
                record = dict(fold=index, phase=phase, arm=arm, start=start.isoformat(), end=end.isoformat(),
                              status="complete", result=asdict(result),
                              metrics=ledger_metrics(trades, protocol["equity"], start, end, policy.observations),
                              trades=ledgers[arm], observations=policy.observations,
                              exit_observations=policy.exit_observations)
                report["comparisons"].append(record)
                print(f"fold={index} phase={phase} arm={arm} trades={len(trades)} net={result.net_pnl_money:.2f}", flush=True)
            if ledgers["adaptive"] != ledgers["adaptive_shadow"]:
                raise AssertionError("ML shadow changed trade ledger")
            checked_ledgers += 1
    report["shadow_ledger_comparisons"] = checked_ledgers
    report["shadow_ledger_invariant"] = True if checked_ledgers else None
    report["improvement_claim"] = False
    report = _finite_json(report)
    (output/"report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    return report


def main() -> None:
    """Freeze or run an offline protocol, never launch the trading orchestrator."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    frozen = commands.add_parser("freeze")
    for name in ("config", "history", "output"):
        frozen.add_argument(f"--{name}", type=Path, required=True)
    frozen.add_argument("--magic", type=int, required=True)
    frozen.add_argument("--start", required=True)
    frozen.add_argument("--end", required=True)
    for name, default in (("train-days", 90), ("validation-days", 30), ("test-days", 30), ("embargo-days", 1)):
        frozen.add_argument(f"--{name}", type=int, default=default)
    frozen.add_argument("--equity", type=float, default=10000)
    frozen.add_argument("--spread-pips", type=float, default=1)
    frozen.add_argument("--commission-per-lot", type=float, default=3.5)
    frozen.add_argument("--slippage-pips", type=float, default=.2)
    frozen.add_argument("--spread-multiplier", type=float, default=1)
    run = commands.add_parser("run")
    run.add_argument("--protocol", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    args = vars(parser.parse_args())
    command = args.pop("command")
    if command == "freeze":
        costs = ExecutionCosts(spread_pips=args.pop("spread_pips"), commission_per_lot=args.pop("commission_per_lot"), slippage_pips=args.pop("slippage_pips"), spread_multiplier=args.pop("spread_multiplier"))
        print(freeze(**args, costs=costs))
    else:
        run_protocol(args.pop("protocol"), args.pop("output"))


if __name__ == "__main__":
    main()
