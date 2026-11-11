from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import HistoricalData
from src.risk.sizing import SymbolTradeInfo
from src.services.config import load_config
from src.tools import backtest_mt5 as b
from src.tools.research_loss_reduction import configurations, closed_atr, atr_gate, account_curve, select_earlier


def bar(t, close=1.1, **kwargs):
    return dict(time=t, open=close, close=close, high=close+.001, low=close-.001, spread=0) | kwargs


@pytest.fixture
def info():
    return SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)


@pytest.fixture
def app():
    return load_config(Path("config/usdchf_m30_research_candidate.json"))


def test_only_declared_strategy_changes_are_applied_and_risk_budget_is_constant(app):
    cfgs = configurations(app.symbols[0], 100)
    base = cfgs["baseline"]
    expected = {"baseline": set(), "atr_trailing": {"max_lot"},
                "atr_fixed2r": {"max_lot", "trailing_stop_mode"},
                "unrestricted_entries": {"max_lot", "allowed_sessions_utc", "max_spread_pips"}}
    for name, cfg in cfgs.items():
        assert {k for k, v in asdict(cfg).items() if v != getattr(base, k)} == expected[name]
        assert cfg.risk_pct == .5 and cfg.one_position_per_symbol and not cfg.ignore_portfolio_cap


def test_atr_uses_only_fifteen_closed_m30_bars_and_not_forming_or_future(info):
    rows = [bar(i*1800) for i in range(17)]
    history = HistoricalData("USDCHF", info, {"M1": [bar(0)], "M30": rows})
    assert closed_atr(history, 15*1800) == pytest.approx(.002)
    rows[15] = bar(15*1800, 9)
    rows[16] = bar(16*1800, 9)
    assert closed_atr(history, 15*1800) == pytest.approx(.002)
    assert closed_atr(history, 14*1800) is None
    rows[14]["high"] = float("nan")
    assert closed_atr(history, 15*1800) is None


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_atr_initial_stop_resizes_position_without_changing_budget_or_mutating_setup(app, info, side):
    cfg = configurations(app.symbols[0], 100)["atr_trailing"]
    history = HistoricalData("USDCHF", info, {"M1": [bar(0)], "M30": [bar(i*1800) for i in range(15)]})
    pending = NS(context={"original": True}, level=1.1, candle_time=14*1800)
    original = b._build_entry_trade
    with atr_gate(history, True):
        t = b._build_entry_trade(cfg, app.runtime, info, 20000, side, 15*1800, 1.1, "key", "paper", pending,
                                 costs=ExecutionCosts(), spread_pips=1)
    assert b._build_entry_trade is original
    assert t is not None and abs(t.entry_price-t.initial_sl) == pytest.approx(.00302)
    assert t.risk_money <= 100 and t.volume == .33
    assert pending.context == {"original": True}
    assert abs(t.initial_tp-(t.entry_price+(-.00002 if side == "BUY" else .00002))) == pytest.approx(.006)


def test_atr_hook_restores_original_on_failure(info, monkeypatch):
    def fail(*a, **k):
        raise RuntimeError("paper failure")
    monkeypatch.setattr(b, "_build_entry_trade", fail)
    with pytest.raises(RuntimeError):
        with atr_gate(None, False):
            b._build_entry_trade(None, None, info, 20000, "BUY", 0, 1.1, "key", "note")
    assert b._build_entry_trade is fail


def trade(start, end, pnl=93):
    utc = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat()
    return b.ClosedTrade("USDCHF", "BUY", utc(start), utc(end), 1.1, 1.101, 1.098, 1.104,
                         1.098, 1.104, 1, pnl, pnl/200, "paper", "ok", "key", commission_cost_money=7)


def test_continuous_equity_includes_floating_pnl_and_excludes_exit_bar_after_fill(info):
    rows = [bar(0, 1.099), bar(60, 1.102), bar(120, 9), bar(180, 9)]
    history = HistoricalData("USDCHF", info, {"M1": rows})
    r = account_curve([trade(0, 180)], history)
    assert r["start_equity"] == 20000 and r["end_equity"] == 20093
    assert r["minimum_sampled_equity"] == pytest.approx(19896.5)
    assert r["peak_sampled_equity"] == pytest.approx(20196.5)
    assert r["m1_close_drawdown"] == pytest.approx(103.5)
    rows[-1] = bar(180, 99)
    assert account_curve([trade(0, 180)], history) == r


def test_account_does_not_reset_between_trades_and_rejects_overlap(info):
    history = HistoricalData("USDCHF", info, {"M1": [bar(i*60) for i in range(10)]})
    r = account_curve([trade(0, 180), trade(240, 360, -107)], history)
    assert r["end_equity"] == 19986
    with pytest.raises(ValueError, match="overlapping"):
        account_curve([trade(0, 180), trade(60, 240)], history)


def test_nomination_ranks_earlier_profit_and_discloses_all_candidates_without_sample_gate():
    records = {"baseline": {"metrics": {"net_pnl": -100}, "account": {"m1_close_drawdown": 150}},
               "candidate": {"metrics": {"net_pnl": 10}, "account": {"m1_close_drawdown": 160}}}
    selected, diagnostics = select_earlier(records)
    assert selected == "candidate"
    assert diagnostics["ranking_by_older_net"] == ["candidate", "baseline"]
