from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from src.backtesting.costs import ExecutionCosts
from src.risk.sizing import SymbolTradeInfo
from src.services.config import load_config
from src.tools import backtest_mt5 as replay
from src.tools.research_reentry import locked, paper_entry_gate


def test_legacy_level_lock_time_distance_and_direction_boundaries():
    previous = {"side": "BUY", "level": 1.1, "time": 1000}
    assert locked(previous, "BUY", 1.1006, 4600, .0001)
    assert not locked(previous, "BUY", 1.10061, 4600, .0001)
    assert not locked(previous, "BUY", 1.1, 4601, .0001)
    assert not locked(previous, "SELL", 1.1, 1000, .0001)
    assert not locked(None, "BUY", 1.1, 1000, .0001)


def test_gate_only_remembers_successful_paper_entries_and_restores_builder(monkeypatch):
    info = NS(digits=5, point=.00001)
    calls = []
    def build(*args, **kwargs):
        calls.append(args)
        return None if len(calls) == 1 else object()
    monkeypatch.setattr(replay, "_build_entry_trade", build)
    pending = NS(level=1.1, candle_time=1000)
    with paper_entry_gate(True) as state:
        args = (None, None, info, 10000, "BUY", 2000, 1.1, "key", "ok", pending)
        assert replay._build_entry_trade(*args) is None
        assert state["previous"] is None
        assert replay._build_entry_trade(*args) is not None
        assert replay._build_entry_trade(*args) is None
        assert len(calls) == 2 and state["blocked"] == 1
    assert replay._build_entry_trade is build
    with paper_entry_gate(True) as fresh:
        assert fresh["previous"] is None


def test_hook_is_restored_on_replay_failure(monkeypatch):
    def build(*a, **k):
        raise RuntimeError("paper failure")
    monkeypatch.setattr(replay, "_build_entry_trade", build)
    with pytest.raises(RuntimeError):
        with paper_entry_gate(False):
            replay._build_entry_trade(None, None, None, 0, "BUY", 0, 0, "key", "note")
    assert replay._build_entry_trade is build


def test_only_gate_changes_and_actual_risk_sizing_is_preserved():
    app = load_config(Path("config/usdchf_m30_research_candidate.json"))
    cfg = app.symbols[0]
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1.1, .00001)
    pending = NS(level=1.1, candle_time=1000, context={})
    args = (cfg, app.runtime, info, 10000, "BUY", 2000, 1.1, "key", "ok", pending)
    costs = {"costs": ExecutionCosts(), "spread_pips": 1}
    with paper_entry_gate(False) as state:
        original = replay._build_entry_trade(*args, **costs)
        assert replay._build_entry_trade(*args, **costs) is not None
        assert state["blocked"] == 0
    with paper_entry_gate(True) as state:
        filtered = replay._build_entry_trade(*args, **costs)
        assert filtered == original
        assert filtered.volume == .04
        assert replay._build_entry_trade(*args, **costs) is None
        assert state["blocked"] == 1
