"""Causality, old-agent parity, weighting and unchanged risk regressions."""
from dataclasses import asdict, replace
from datetime import datetime
from types import SimpleNamespace

import pytest

from src.backtesting.swaps import SwapModel
from src.engine.orchestrator import compute_r_multiple_trailing_stop
from src.risk.sizing import SymbolTradeInfo
from src.services.config import load_config
from src.strategy.adaptive_direction_agent import AdviceConfig, fit_advice, update_boundary
from src.strategy.cost_aware_agent import ClosedOutcome, fit_month
from src.tools import backtest_mt5 as replay
from src.tools.research_agent_improvement import VARIANTS, advice_config, adviser_gate, task, nominate
from src.tools.research_usdchf_risk05 import settings


def ts(value):
    return int(datetime.fromisoformat(value+"+00:00").timestamp())


def test_default_advice_exactly_matches_old_agent_including_ties_and_cold_start():
    stamp = ts("2026-02-16T10:00")
    boundary = ts("2026-02-01T00:00")
    data = [ClosedOutcome(boundary-1-i*86400, s, (i%3)-.8) for s in ("BUY", "SELL") for i in range(20)]
    for rows in ([], data[:7], data, data+[ClosedOutcome(boundary, "BUY", 999)]):
        assert asdict(fit_advice(rows, stamp, AdviceConfig())) == asdict(fit_month(rows, stamp, best_only=True))


def test_weekly_boundary_is_monday_utc_and_cannot_use_current_week_exit():
    config = AdviceConfig(cadence="weekly")
    monday = ts("2026-02-09T00:00")
    assert update_boundary(monday-1, config) == ts("2026-02-02T00:00")
    assert update_boundary(monday+6*86400+86399, config) == monday
    rows = [ClosedOutcome(monday-1, "BUY", .5)]*8
    frozen = fit_advice(rows, monday, config)
    assert frozen.allowed_sides == ("BUY",)
    rows += [ClosedOutcome(monday, "SELL", 999)]*20
    assert fit_advice(rows, monday+5*86400, config) == frozen
    assert fit_advice(rows, monday+7*86400, config).allowed_sides == ("SELL",)


@pytest.mark.parametrize("days", [90, 180, 365])
def test_memory_window_includes_exact_oldest_boundary_and_excludes_future(days):
    boundary = ts("2026-02-01T00:00")
    oldest = boundary-days*86400
    rows = [ClosedOutcome(oldest, "BUY", 1)]*8
    rows += [ClosedOutcome(oldest-1, "SELL", 999), ClosedOutcome(boundary, "SELL", 999)]*20
    advice = fit_advice(rows, boundary, AdviceConfig(lookback_days=days))
    assert advice.counts == (8, 0) and advice.allowed_sides == ("BUY",)
    assert advice.last_training_exit == oldest


def test_recency_weights_have_declared_half_life_and_do_not_relax_sample_minimum():
    boundary = ts("2026-02-01T00:00")
    rows = [ClosedOutcome(boundary-60*86400, "BUY", -1)]*8
    rows += [ClosedOutcome(boundary-120*86400, "BUY", 2)]*8
    plain = fit_advice(rows, boundary, AdviceConfig())
    weighted = fit_advice(rows, boundary, AdviceConfig(half_life_days=60))
    assert plain.mean_net_r[0] == .5 and plain.allowed_sides == ("BUY",)
    assert weighted.mean_net_r[0] == pytest.approx(0) and weighted.allowed_sides == ()
    assert fit_advice([ClosedOutcome(boundary-1, "BUY", 100)]*7, boundary,
                      AdviceConfig(half_life_days=60)).allowed_sides == ()


@pytest.mark.parametrize("kwargs", [dict(cadence="daily"), dict(lookback_days=0),
    dict(lookback_days=True), dict(minimum_trades=1.5), dict(half_life_days=0),
    dict(half_life_days=float("nan")), dict(half_life_days=float("inf"))])
def test_invalid_advice_configuration_rejected(kwargs):
    with pytest.raises(ValueError):
        AdviceConfig(**kwargs)


def test_each_hypothesis_changes_one_parameter_and_retains_risk_guards(tmp_path):
    app = load_config(tmp_path/"defaults.json")
    source = SimpleNamespace(config=app, symbol=replace(app.symbols[0], symbol="USDCHF", timeframe="M30", sl_pips=20))
    app, cfg, _ = settings(source, SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001))
    expected = {"baseline": set(), "weekly": {"cadence"}, "lookback_90": {"lookback_days"},
                "lookback_365": {"lookback_days"}, "recent_weighted": {"half_life_days"}, "trail_gap_1_25": set()}
    default = AdviceConfig()
    for v in VARIANTS:
        job, config, outcomes = task(v, 2, "full", True, app, cfg, SwapModel(1, -20))
        assert {k for k, x in asdict(config).items() if x != getattr(default, k)} == expected[v]
        assert config.minimum_trades == 8
        assert {k for k, x in asdict(cfg).items() if x != getattr(job[3], k)} == ({"trailing_gap_r"} if v == "trail_gap_1_25" else set())
        assert job[2].runtime == app.runtime and job[8] == 10000 and job[3].risk_pct == .5
        assert job[3].sl_pips == 20 and job[3].max_lot == .5 and job[3].max_spread_pips == .9
        assert job[7].debit_multiplier == 2 and job[6].commission_per_lot == 7


def test_gate_updates_only_at_boundary_delegates_sizing_and_restores_after_exception(monkeypatch):
    monday = ts("2026-02-09T00:00")
    rows = [ClosedOutcome(monday-1, "BUY", 1)]*8+[ClosedOutcome(monday, "SELL", 10)]*8
    calls = []
    def original(*args, **kwargs):
        calls.append((args, kwargs))
        return "risk-sized"
    monkeypatch.setattr(replay, "_build_entry_trade", original)
    with pytest.raises(RuntimeError):
        with adviser_gate(rows, AdviceConfig(cadence="weekly")) as (fits, decisions):
            assert replay._build_entry_trade(1, 2, 3, 10000, "SELL", monday) is None
            assert replay._build_entry_trade(1, 2, 3, 10000, "BUY", monday+100, pending="risk") == "risk-sized"
            assert len(calls) == 1 and calls[0][1] == {"pending": "risk"}
            assert replay._build_entry_trade(1, 2, 3, 10000, "SELL", monday+7*86400) == "risk-sized"
            assert len(fits) == 2 and len(decisions) == 3
            raise RuntimeError("stop replay")
    assert replay._build_entry_trade is original


@pytest.mark.parametrize("side,sign", [("BUY", 1), ("SELL", -1)])
def test_larger_candidate_trailing_gap_never_widens_an_existing_stop(side, sign):
    stop = 1.1-sign*.002
    for move in (1, 1.5, 3, 1.6, .2, 4):
        target = compute_r_multiple_trailing_stop(side=side, open_price=1.1,
            current_exit_price_value=1.1+sign*.002*move, current_sl=stop,
            risk_distance_price=.002, activation_r=1.5, gap_r=1.25)
        if target is not None:
            assert sign*(target-stop) >= 0
            stop = target


def test_selection_cannot_use_later_winners_or_promote_zero_trade_cash():
    records = {v+"_gmt3_stress": {"earlier": {"metrics": {"net_pnl": 0},
        "account": {"m1_close_drawdown": 0}}, "later": 999999} for v in VARIANTS}
    assert nominate(records)[0] == "cash"
    records["weekly_gmt3_stress"]["earlier"]["metrics"]["net_pnl"] = 1
    assert nominate(records)[0] == "weekly"
