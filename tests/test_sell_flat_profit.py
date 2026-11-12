"""Profit research may vary one parameter at a time, never risk controls."""
from dataclasses import asdict, replace

import pytest

from src.engine.orchestrator import compute_r_multiple_trailing_stop
from src.services.config import load_config
from src.tools.research_sell_flat_profit import configurations, nominate


def test_hypotheses_are_isolated_and_preserve_initial_risk_and_exit_activation(tmp_path):
    base = replace(load_config(tmp_path/"defaults.json").symbols[0], risk_pct=.75,
                   max_lot=.5, sl_pips=20, rr=2, max_spread_pips=.9, trailing_activation_r=1.5,
                   confirmation_displacement_range_multiple=1.8)
    configs = configurations(base)
    fields = {"spread_0_7": "max_spread_pips", "stronger_confirmation": "confirmation_displacement_range_multiple",
              "trailing_gap_1_25": "trailing_gap_r"}
    assert configs["baseline"] == base
    for name, field in fields.items():
        changed = {k for k, v in asdict(configs[name]).items() if v != asdict(base)[k]}
        assert changed == {field}
        assert configs[name].risk_pct == .75
        assert configs[name].sl_pips == 20
        assert configs[name].trailing_activation_r == 1.5


def test_nomination_uses_earlier_stressed_net_and_reports_negative_results():
    def record(net, dd):
        return {"metrics": {"net_pnl": net}, "account": {"m1_close_drawdown": dd}}
    rows = {"baseline": record(-234, 400), "candidate": record(-100, 500)}
    assert nominate(rows) == ("candidate", ["candidate", "baseline"])
    rows["other"] = record(-100, 450)
    assert nominate(rows)[0] == "other"
    rows["a"] = record(-100, 450)
    assert nominate(rows)[0] == "a"


@pytest.mark.parametrize("side,sign", [("BUY", 1), ("SELL", -1)])
def test_larger_configured_gap_cannot_widen_an_already_tightened_stop(side, sign):
    kwargs = dict(side=side, open_price=1.1, risk_distance_price=.002,
                  activation_r=1.5, gap_r=1.25)
    first = compute_r_multiple_trailing_stop(current_exit_price_value=1.1+sign*.0031,
        current_sl=1.1-sign*.002, **kwargs)
    assert first is not None
    assert sign*(first-(1.1-sign*.002)) > 0
    # A pullback can never relax the already locked stop to save the position.
    next_stop = compute_r_multiple_trailing_stop(current_exit_price_value=1.1+sign*.003,
        current_sl=first, **kwargs)
    assert next_stop is None or sign*(next_stop-first) >= 0
