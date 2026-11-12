"""Causal adviser regression tests; no broker or execution capability required."""
from dataclasses import asdict, replace
from datetime import datetime
from types import SimpleNamespace

import pytest

from src.backtesting.costs import ExecutionCosts
from src.backtesting.swaps import SwapModel
from src.risk.sizing import SymbolTradeInfo
from src.services.config import load_config
from src.strategy.cost_aware_agent import ClosedOutcome, fit_month, month_start
from src.tools import backtest_mt5 as replay
from src.tools.research_direction_agent import VARIANTS, adviser_gate, nominate, task
from src.tools.research_usdchf_risk05 import settings


def ts(value):
    return int(datetime.fromisoformat(value+"+00:00").timestamp())


def test_future_current_month_and_just_closed_boundary_outcomes_are_excluded():
    boundary = ts("2026-02-01T00:00")
    data = [ClosedOutcome(boundary-1, "BUY", 1) for _ in range(8)]
    before = fit_month(data, boundary)
    data += [ClosedOutcome(boundary, "BUY", -999), ClosedOutcome(boundary+100, "SELL", 999)]*20
    assert fit_month(data, boundary+20*86400) == before
    assert before.allowed_sides == ("BUY",) and before.last_training_exit == boundary-1
    assert before.counts == (8, 0)


def test_180_day_boundary_and_sample_shortfall_and_zero_expectancy():
    boundary = ts("2026-02-01T00:00")
    oldest = boundary-180*86400
    data = [ClosedOutcome(oldest-1, "BUY", 100)]*20
    data += [ClosedOutcome(oldest, "BUY", 1)]*7
    data += [ClosedOutcome(boundary-1, "SELL", 0)]*8
    advice = fit_month(data, boundary)
    assert advice.counts == (7, 8) and advice.allowed_sides == ()
    assert fit_month(data+[ClosedOutcome(oldest, "BUY", 1)], boundary).allowed_sides == ("BUY",)
    assert fit_month([], boundary).last_training_exit is None


def test_best_side_and_stable_tie_vs_all_positive_sides():
    boundary = ts("2026-02-01T00:00")
    rows = [ClosedOutcome(boundary-1, s, 1) for s in ("BUY", "SELL") for _ in range(8)]
    assert fit_month(rows, boundary).allowed_sides == ("BUY", "SELL")
    assert fit_month(rows, boundary, best_only=True).allowed_sides == ("BUY",)
    rows += [ClosedOutcome(boundary-1, "SELL", 2)]
    assert fit_month(rows, boundary, best_only=True).allowed_sides == ("SELL",)


@pytest.mark.parametrize("side,net", [("HOLD", 1), ("BUY", float("nan")), ("SELL", float("inf"))])
def test_bad_labels_rejected(side, net):
    with pytest.raises(ValueError):
        ClosedOutcome(1, side, net)


def test_month_uses_utc_and_rolls_exactly_at_boundary():
    assert month_start(ts("2026-01-31T23:59")) == ts("2026-01-01T00:00")
    assert month_start(ts("2026-02-01T00:00")) == ts("2026-02-01T00:00")


def test_gate_delegates_risk_sizing_unchanged_and_restores_on_failure(monkeypatch):
    stamp = ts("2026-02-01T01:00")
    labels = [ClosedOutcome(stamp-7200, "BUY", .2)]*8
    calls = []
    def original(*args, **kwargs):
        calls.append((args, kwargs))
        return "sized-by-existing-risk-manager"
    monkeypatch.setattr(replay, "_build_entry_trade", original)
    with pytest.raises(RuntimeError):
        with adviser_gate(labels, False) as (months, decisions):
            assert replay._build_entry_trade(1, 2, 3, 10000, "SELL", stamp) is None
            assert calls == []
            assert replay._build_entry_trade(1, 2, 3, 10000, "BUY", stamp, "price", pending="setup") == "sized-by-existing-risk-manager"
            assert calls == [((1, 2, 3, 10000, "BUY", stamp, "price"), {"pending": "setup"})]
            assert len(months) == 1 and [d["allow"] for d in decisions] == [False, True]
            raise RuntimeError("replay stopped")
    assert replay._build_entry_trade is original


def test_new_variants_change_only_direction_or_disable_trailing(tmp_path):
    config = load_config(tmp_path/"defaults.json")
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)
    app, cfg, _ = settings(SimpleNamespace(config=config, symbol=replace(config.symbols[0], symbol="USDCHF", timeframe="M30", sl_pips=20)), info)
    for v in VARIANTS:
        job, variant, outcomes = task(v, 2, "full", True, app, cfg, SwapModel(1, -20))
        changed = {k for k, value in asdict(cfg).items() if value != getattr(job[3], k)}
        expected = {"trade_side_filter"} if v in {"buy_only", "sell_only"} else {"trailing_stop_mode"} if v == "fixed_2r" else set()
        assert changed == expected
        assert job[2].runtime == app.runtime and job[3].risk_pct == .5 and job[8] == 10000
        assert job[3].max_spread_pips == .9 and job[3].max_lot == .5 and job[3].sl_pips == 20
        assert job[6] == ExecutionCosts("historical", 2, 7, .4)
        assert job[7].debit_multiplier == 2 and job[9].mode == "triple_only"


def test_earlier_selection_uses_cash_and_never_later_winner():
    rows = {v+"_gmt3_stress": {"earlier": {"metrics": {"net_pnl": -1},
        "account": {"m1_close_drawdown": 10}}, "later": {"metrics": {"net_pnl": 999999}}} for v in VARIANTS}
    assert nominate(rows)[0] == "cash"
    rows["buy_only_gmt3_stress"]["earlier"]["metrics"]["net_pnl"] = 1
    assert nominate(rows)[0] == "buy_only"
