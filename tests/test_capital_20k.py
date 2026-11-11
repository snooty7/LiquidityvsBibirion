from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.backtesting.costs import ExecutionCosts
from src.risk.sizing import SymbolTradeInfo
from src.services.config import load_config
from src.tools import backtest_mt5 as replay
from src.tools.research_capital_20k import CAPITAL, RISKS, PAPER_LOT_CAP, outcomes


def trade(pnl):
    return replay.ClosedTrade("USDCHF", "BUY", datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
        datetime(2026, 1, 2, tzinfo=timezone.utc).isoformat(), 1.1, 1.1, 1.098, 1.104,
        1.098, 1.104, .1, pnl, pnl/20, "paper", "ok", "key")


def test_successful_trade_target_is_separate_from_average_including_losses():
    result = outcomes([trade(p) for p in (150, 200, 250, 99, 100, -80, -100, 0)])
    assert result["mean_winner"] == pytest.approx(159.8)
    assert result["mean_loser"] == -90
    assert result["mean_all"] == pytest.approx(619/8)
    assert result["wins_100_to_200"] == 3
    assert result["wins_at_least_100"] == 4 and result["wins_above_200"] == 1
    assert result["largest_loss"] == -100
    assert outcomes([])["mean_winner"] == 0


def test_twenty_thousand_sizing_uses_risk_and_keeps_portfolio_guard():
    app = load_config(Path("config/usdchf_m30_research_candidate.json"))
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1.1, .00001)
    volumes = []
    for risk in RISKS:
        cfg = replace(app.symbols[0], risk_pct=risk, max_lot=PAPER_LOT_CAP)
        result = replay._build_entry_trade(cfg, app.runtime, info, CAPITAL, "BUY", 0, 1.1, "key", "paper",
                                           costs=ExecutionCosts(), spread_pips=1)
        assert result is not None
        assert result.risk_money <= CAPITAL*risk/100
        assert cfg.sl_pips == 20 and app.runtime.daily_loss_limit_usd == 150
        volumes.append(result.volume)
    assert volumes == [.09, .18, .27, .45]
    strict = replace(app.runtime, max_total_open_risk_pct=.2)
    assert replay._build_entry_trade(cfg, strict, info, CAPITAL, "BUY", 0, 1.1, "key", "paper",
                                     costs=ExecutionCosts(), spread_pips=1) is None
