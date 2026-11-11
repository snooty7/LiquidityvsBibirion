from dataclasses import asdict
from pathlib import Path

import pytest

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import HistoricalData
from src.risk.sizing import SymbolTradeInfo
from src.services.config import load_config
from src.tools.research_capital_20k import outcomes
from src.tools.research_loss_reduction import account_curve
from src.tools.research_spread_resilience import configurations, code_hash, nominate
from src.tools.render_spread_resilience import audit
from src.tools.walk_forward import RISK_KEYS


def empty_study():
    app = load_config(Path("config/usdchf_m30_research_candidate.json"))
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)
    h = HistoricalData("USDCHF", info, {"M1": []})
    cfgs = configurations(app.symbols[0])
    windows = {phase: {"start": "2025-01-01T00:00:00+00:00", "end_exclusive": "2026-01-01T00:00:00+00:00"}
               for phase in ("earlier", "later", "full")}
    comparison = {name: {phase: {"name": name, "phase": phase,
        **windows[phase.removesuffix("_stress")], **outcomes([]), "account": account_curve([], h), "trades": []}
        for phase in ("earlier", "earlier_stress", "later", "later_stress", "full", "full_stress")} for name in cfgs}
    selected, ranking = nominate({n: v["earlier_stress"] for n, v in comparison.items()})
    report = {"plan": {"settings": {n: asdict(c) for n, c in cfgs.items()}, "windows": windows,
        "replay_code_sha256": code_hash(), "history_sha256": h.digest(),
        "costs": asdict(ExecutionCosts()), "stress_costs": asdict(ExecutionCosts("historical", 2, 7, .4)),
        "risk_runtime": {k: getattr(app.runtime, k) for k in RISK_KEYS}},
        "comparison": comparison, "locked_selection": {"selected": selected, "earlier_stress_ranking": ranking},
        "descriptive_checks": {n: {"full_base_profitable": False, "full_stress_profitable": False,
            "later_stress_profitable": False, "winning_trade_goal": False} for n in cfgs},
        "nominee_meets_historical_objective": False}
    return report, h


def test_empty_study_audit_cannot_claim_a_success_or_hide_unprofitable_scenarios():
    report, history = empty_study()
    result = audit(report, history)
    assert result["passed"] and result["continuous_replays"] == 30
    assert not report["nominee_meets_historical_objective"]


@pytest.mark.parametrize("corruption", ["costs", "risk", "claim", "goal", "phase", "metric", "selection"])
def test_audit_rejects_changed_protections_costs_or_false_positive_claims(corruption):
    report, history = empty_study()
    if corruption == "costs":
        report["plan"]["stress_costs"]["commission_per_lot"] = 0
    elif corruption == "risk":
        report["plan"]["risk_runtime"]["daily_loss_limit_usd"] = 0
    elif corruption == "claim":
        report["nominee_meets_historical_objective"] = True
    elif corruption == "goal":
        report["descriptive_checks"]["baseline"]["winning_trade_goal"] = True
    elif corruption == "phase":
        report["comparison"]["baseline"].pop("full_stress")
    elif corruption == "metric":
        report["comparison"]["baseline"]["full_stress"]["mean_winner"] = 150
    else:
        report["locked_selection"]["selected"] = "fresh_confirmation"
    with pytest.raises(ValueError):
        audit(report, history)
