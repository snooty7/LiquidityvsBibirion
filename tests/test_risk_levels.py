from dataclasses import asdict, replace
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.backtesting.costs import ExecutionCosts
from src.execution.mt5_adapter import MT5Adapter
from src.risk.sizing import SymbolTradeInfo
from src.services.config import load_config
from src.tools import backtest_mt5 as replay
from src.tools import research_risk_levels as study
from src.tools import render_risk_levels as reporting


@pytest.fixture
def app():
    return load_config(Path("config/usdchf_m30_research_candidate.json"))


@pytest.fixture
def info():
    return SymbolTradeInfo(5, .00001, .01, 100, .01, 1.1, .00001)


def test_risk_scenarios_change_only_budget_and_declared_reference_spread(app):
    variants = study.variants(app.symbols[0])
    assert len(variants) == 8
    assert set(cfg.risk_pct for cfg in variants.values()) == {.1, .2, .3, .5}
    base = variants["baseline_risk_0.1"]
    for name, cfg in variants.items():
        changed = {key for key, value in asdict(base).items() if getattr(cfg, key) != value}
        assert changed <= {"risk_pct", "max_spread_pips"}
        assert cfg.max_lot == .05 and cfg.sl_pips == 20 and not cfg.ignore_portfolio_cap
        assert cfg.max_spread_pips == (.9 if name.startswith("spread_0_9") else 1.8)


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_increased_budget_plateaus_at_same_lot_cap_and_keeps_portfolio_guard(app, info, monkeypatch, side):
    def forbidden(*a, **k):
        raise AssertionError("No broker or trade calls allowed")
    monkeypatch.setattr(MT5Adapter, "initialize", forbidden)
    monkeypatch.setattr(MT5Adapter, "send_market_order_with_price_protection", forbidden)
    variants = study.variants(app.symbols[0])
    volumes = []
    for risk in study.RISK_LEVELS:
        cfg = variants[f"baseline_risk_{risk:g}"]
        trade = replay._build_entry_trade(cfg, app.runtime, info, 10000, side, 1000, 1.1, "key", "ok",
                                          costs=ExecutionCosts(), spread_pips=1)
        assert trade is not None
        volumes.append(trade.volume)
        assert abs(trade.entry_price-trade.initial_sl) == pytest.approx(.00202)
        assert trade.risk_money <= 10000*risk/100
        strict_runtime = replace(app.runtime, max_total_open_risk_pct=.05)
        assert replay._build_entry_trade(cfg, strict_runtime, info, 10000, side, 1000, 1.1, "key", "ok",
                                         costs=ExecutionCosts(), spread_pips=1) is None
    assert volumes == [.04, .05, .05, .05]


def closed(pnl, index=0, volume=.04):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)+timedelta(minutes=index*2)
    return replay.ClosedTrade(symbol="USDCHF", side="BUY", entry_time_utc=start.isoformat(),
        exit_time_utc=(start+timedelta(minutes=1)).isoformat(), entry_price=1.1, exit_price=1.1,
        sl_initial=1.098, tp_initial=1.104, exit_sl=1.098, exit_tp=1.104, volume=volume,
        pnl_money=pnl, pnl_r=pnl/10, reason="test", confirm_note="ok", signal_key=str(index))


def test_loss_streak_count_and_cash_are_distinct_and_zero_breaks_a_run():
    trades = [closed(pnl, i) for i, pnl in enumerate([-1, -1, -1, 1, -10, -10, 0, -1])]
    result = study.loss_streaks(list(reversed(trades)))
    assert result == {"max_consecutive_losses": 3, "worst_loss_streak_money": 20}
    assert study.loss_streaks([]) == {"max_consecutive_losses": 0, "worst_loss_streak_money": 0}


def test_risk_metrics_use_current_entry_equity_and_reject_cap_or_budget_breaches(app, info):
    cfg = study.variants(app.symbols[0])["baseline_risk_0.1"]
    first, second = closed(-100), closed(20, 1)
    record = study.record_metrics([first, second], cfg, info)
    assert record["metrics"]["net_pnl"] == -80
    assert record["max_initial_stop_risk_pct"] == pytest.approx(8.8/9900*100)
    assert record["volumes"] == {"0.04": 2}
    assert record["at_lot_cap"] == 0
    with pytest.raises(ValueError, match="lot cap"):
        study.record_metrics([closed(0, volume=.06)], cfg, info)
    with pytest.raises(ValueError, match="budget"):
        study.record_metrics([closed(-2000), second], cfg, info)


def test_risk_metrics_reject_overlapping_positions(app, info):
    cfg = study.variants(app.symbols[0])["baseline_risk_0.1"]
    with pytest.raises(ValueError, match="Overlapping"):
        study.record_metrics([closed(-1), closed(-1)], cfg, info)


def empty_report(app, info):
    cfgs = study.variants(app.symbols[0])
    rows, comparison = [], {}
    for name, cfg in cfgs.items():
        empty = study.record_metrics([], cfg, info)
        comparison[name] = {scope: deepcopy(empty) for scope in (
            "earlier_year", "earlier_year_stress", "test_year", "confirmation", "stress_confirmation")}
        for phase, indices in (("earlier_base", [0]), ("earlier_stress", [0]),
                               ("test_base", range(1, 13)), ("test_stress", range(7, 13))):
            for index in indices:
                rows.append({"name": name, "phase": phase, "fold": index,
                             "start": "2026-01-01T00:00:00+00:00", "end_exclusive": "2026-01-02T00:00:00+00:00",
                             **deepcopy(empty)})
    return {"plan": {"settings": {n: asdict(c) for n, c in cfgs.items()},
                     "symbol_info": asdict(info), "risk_runtime": {"daily_loss_limit_usd": 150,
                     "max_total_open_risk_pct": .5}},
            "rows": rows, "comparison": comparison, "unique_replays": 160}


def test_sizing_report_audits_all_scenarios_and_resets_equity_per_replay(app, info):
    assert reporting.audit(empty_report(app, info), [])["passed"]


@pytest.mark.parametrize("corruption", ["missing", "lot_cap", "stop_rule", "portfolio", "risk_metric"])
def test_sizing_audit_rejects_missing_results_weakened_guards_or_wrong_risk(app, info, corruption):
    report = empty_report(app, info)
    if corruption == "missing":
        report["rows"].pop()
    elif corruption == "lot_cap":
        report["plan"]["settings"]["baseline_risk_0.2"]["max_lot"] = .1
    elif corruption == "stop_rule":
        report["plan"]["settings"]["baseline_risk_0.2"]["trailing_gap_r"] = 2
    elif corruption == "portfolio":
        report["plan"]["risk_runtime"]["max_total_open_risk_pct"] = 1
    else:
        report["rows"][0]["max_initial_stop_risk_pct"] = .5
    with pytest.raises(ValueError):
        reporting.audit(report, [])
