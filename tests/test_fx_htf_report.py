from copy import deepcopy
from dataclasses import asdict

import pytest

from src.backtesting.costs import ExecutionCosts
from src.services.config import load_config
from src.tools.render_fx_htf import audit
from src.tools.research_fx_htf import SYMBOLS, MODELS, models
from src.tools.walk_forward import trade_metrics


def empty_report(tmp_path):
    base = load_config(tmp_path / "defaults.json").symbols[0]
    m = trade_metrics([], 10000)
    rows = [{"symbol": s, "name": n, "fold": i, "phase": phase, "scenario": scenario,
             "start": "2026-01-01T00:00:00+00:00", "end_exclusive": "2026-01-31T00:00:00+00:00",
             "metrics": deepcopy(m)}
            for s in SYMBOLS for n in MODELS
            for phase, scenario, indices in (("train", "base", range(1, 13)),
                ("test", "base", range(1, 13)), ("test", "stress", range(7, 13))) for i in indices]
    return {"rows": rows, "unique_replays": 270,
            "plan": {"settings": {s: {n: asdict(c) for n, c in models(base, s).items()} for s in SYMBOLS},
                     "costs": asdict(ExecutionCosts()), "stress_costs": asdict(ExecutionCosts("historical", 2, 7, .4))},
            "comparison": {s: {n: {scope: {"metrics": deepcopy(m)} for scope in
                ("aggregate", "confirmation", "stress_confirmation")} for n in MODELS} for s in SYMBOLS}}


def test_complete_empty_study_audits_each_pair_as_an_independent_account(tmp_path):
    result = audit(empty_report(tmp_path), [])
    assert result["passed"] and result["all_replays_present"] == 270
    assert set(result["accounts_audited_separately"]) == set(SYMBOLS)
    assert all(r["test_rows_recomputed"] == 54 for r in result["accounts_audited_separately"].values())
    assert result["no_portfolio_return_inferred"]


@pytest.mark.parametrize("corruption", ["missing", "duplicate", "count", "unknown_symbol", "metric"])
def test_audit_rejects_missing_mixed_or_misreported_market_results(tmp_path, corruption):
    report, trades = empty_report(tmp_path), []
    if corruption == "missing":
        report["rows"].pop()
    elif corruption == "duplicate":
        report["rows"][-1] = report["rows"][0]
    elif corruption == "count":
        report["unique_replays"] = 269
    elif corruption == "unknown_symbol":
        trades.append({"symbol": "BTCUSD"})
    else:
        next(r for r in report["rows"] if r["phase"] == "test")["metrics"]["net_pnl"] = 1
    with pytest.raises(ValueError):
        audit(report, trades)
