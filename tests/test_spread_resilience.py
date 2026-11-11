from dataclasses import asdict
from pathlib import Path

import pytest

from src.backtesting.costs import ExecutionCosts
from src.engine.orchestrator import compute_r_multiple_trailing_stop, effective_trailing_settings
from src.risk.sizing import SymbolTradeInfo
from src.services.config import load_config
from src.tools import backtest_mt5 as replay
from src.tools.research_spread_resilience import configurations, nominate


@pytest.fixture
def app():
    return load_config(Path("config/usdchf_m30_research_candidate.json"))


def test_four_hypotheses_change_exactly_one_declared_setting_each(app):
    cfgs = configurations(app.symbols[0])
    baseline = cfgs["baseline"]
    expected = {"baseline": set(), "trail_later_1_5": {"trailing_activation_r"},
                "trail_gap_1_25": {"trailing_gap_r"},
                "stronger_confirmation": {"confirmation_displacement_range_multiple"},
                "fresh_confirmation": {"confirm_expiry_bars"}}
    assert len(cfgs) == 5
    for name, cfg in cfgs.items():
        assert {k for k, v in asdict(cfg).items() if v != getattr(baseline, k)} == expected[name]
        assert cfg.risk_pct == .5 and cfg.max_lot == .5 and cfg.max_spread_pips == .9
        assert cfg.sl_pips == 20 and cfg.rr == 2 and cfg.one_position_per_symbol
        assert not cfg.ignore_portfolio_cap
    assert baseline.confirm_expiry_bars == 5
    assert baseline.confirmation_displacement_range_multiple == 1.8


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_every_variant_keeps_identical_initial_position_risk_and_sizing(app, side):
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1.1, .00001)
    positions = [replay._build_entry_trade(cfg, app.runtime, info, 20000, side, 1000, 1.1, "key", "paper",
                                          costs=ExecutionCosts(), spread_pips=.8)
                 for cfg in configurations(app.symbols[0]).values()]
    assert all(p is not None for p in positions)
    assert all(p == positions[0] for p in positions)
    assert positions[0].volume == .45 and positions[0].risk_money <= 100


@pytest.mark.parametrize("name", ["trail_later_1_5", "trail_gap_1_25"])
@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_new_trailing_settings_never_widen_an_existing_stop(app, name, side):
    cfg = configurations(app.symbols[0])[name]
    mode, activation, gap, remove_tp = effective_trailing_settings(cfg, app.runtime)
    assert mode == "r_multiple" and remove_tp
    entry, initial_risk = 1.1, .002
    stop = entry-initial_risk if side == "BUY" else entry+initial_risk
    for move_r in (0.5, 1., 1.5, 1.8, .6, 2.5, 1.):
        quote = entry+(move_r*initial_risk if side == "BUY" else -move_r*initial_risk)
        desired = compute_r_multiple_trailing_stop(side=side, open_price=entry,
            current_exit_price_value=quote, current_sl=stop, risk_distance_price=initial_risk,
            activation_r=activation, gap_r=gap)
        if desired is not None:
            assert desired >= stop if side == "BUY" else desired <= stop
            stop = desired


def test_nominee_uses_only_earlier_stressed_net_with_deterministic_drawdown_ties():
    def record(net, dd):
        return {"metrics": {"net_pnl": net}, "account": {"m1_close_drawdown": dd}}
    earlier = {"baseline": record(-500, 700), "better": record(-100, 300), "riskier": record(-100, 400)}
    selected, ranking = nominate(earlier)
    assert selected == "better" and ranking == ["better", "riskier", "baseline"]
    # The selector has no access to later or full-history metrics.
    earlier["riskier"]["later_net"] = 100000
    assert nominate(earlier)[0] == "better"
