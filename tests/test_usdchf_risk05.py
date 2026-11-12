"""Matched risk study may change SELL rollover policy, never comparison funding/risk."""
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from src.backtesting.costs import ExecutionCosts
from src.backtesting.swaps import SwapModel
from src.risk.sizing import SymbolTradeInfo, calc_position_risk_money
from src.services.config import load_config
from src.tools.research_usdchf_risk05 import CAPITAL, RISK_PCT, legacy_task, settings
from src.tools.backtest_mt5 import PendingSetupLite, _build_entry_trade


def test_old_new_groups_use_requested_half_percent_and_same_trailing(tmp_path):
    config = load_config(tmp_path/"defaults.json")
    source = SimpleNamespace(config=config, symbol=replace(config.symbols[0], symbol="USDCHF"))
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)
    app, old, new = settings(source, info)
    assert CAPITAL == 10000 and RISK_PCT == .5
    assert old.risk_pct == new.risk_pct == app.runtime.max_total_open_risk_pct == .5
    assert old.trailing_activation_r == new.trailing_activation_r == 1.5
    assert old.timeframe == source.symbol.timeframe and new.timeframe == "M1"
    assert new.bias_timeframe == "M5" and new.max_lot == info.volume_max
    assert old.max_lot == .5 and old.sl_pips == source.symbol.sl_pips
    assert app.runtime.daily_loss_limit_usd == config.runtime.daily_loss_limit_usd


def test_paired_old_tasks_differ_only_by_overnight_policy_and_label(tmp_path):
    config = load_config(tmp_path/"defaults.json")
    cfg = replace(config.symbols[0], risk_pct=.5)
    swap = SwapModel(1, -20)
    a = legacy_task("original", 3, "full", True, config, cfg, swap)
    b = legacy_task("sell_flat", 3, "full", True, config, cfg, swap)
    assert a[1:9] == b[1:9]
    assert a[9] is None and b[9].sides == ("SELL",)
    assert a[8] == b[8] == 10000
    assert asdict(a[6]) == asdict(b[6])
    assert a[7].debit_multiplier == b[7].debit_multiplier == 2
    assert a[7].buy_per_lot == b[7].buy_per_lot == 1


@pytest.mark.parametrize("side,sign", [("BUY", 1), ("SELL", -1)])
def test_new_entry_actual_fill_risk_is_half_percent_not_previous_three_quarters(tmp_path, side, sign):
    config = load_config(tmp_path/"defaults.json")
    source = SimpleNamespace(config=config, symbol=replace(config.symbols[0], symbol="USDCHF"))
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)
    app, _, scalp = settings(source, info)
    setup = PendingSetupLite("key", side, 1.1, 0, 60,
        context={"risk": {"sl_price": 1.1-sign*.0006, "tp_r_multiple": 2}})
    trade = _build_entry_trade(scalp, app.runtime, info, CAPITAL, side, 0, 1.1, "key", "test", setup,
                               costs=ExecutionCosts(), spread_pips=.7)
    assert trade is not None and trade.volume > .5
    money = calc_position_risk_money(trade.entry_price, trade.sl, trade.volume, info)
    assert 49 <= money <= 50
    assert trade.sl == setup.context["risk"]["sl_price"]
