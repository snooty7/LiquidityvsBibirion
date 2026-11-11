from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
import json

import pytest

from src.engine import orchestrator as live
from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import HistoricalData
from src.execution.mt5_adapter import MT5Adapter
from src.persistence.repository import SQLiteRepository
from src.risk.sizing import SymbolTradeInfo
from src.services.config import load_config
from src.strategy.htf_models import HTF_MODES, detect_htf_signal
from src.tools import backtest_mt5 as replay
from src.tools.research_fx_htf import models, PROTECTED
from src.tools.walk_forward import history_coverage


def candle(time, close, **overrides):
    return dict(time=time, open=close-.00001, close=close, high=close+.00002, low=close-.00002) | overrides


def pattern(mode, side="BUY"):
    # All H4 candles have closed by the H1 decision.
    entry = [candle(1000800+i*3600, 1.1+i*.00002) for i in range(150)]
    end = entry[-1]["time"]+3600
    bias_end = (end-14400)//14400*14400
    macro = [candle(bias_end-(149-i)*14400, 1.03+i*.0005) for i in range(150)]
    if mode == "htf_trend_pullback":
        entry[-2] = candle(entry[-2]["time"], 1.1026, open=1.10275, low=1.1025, high=1.1028)
        entry[-1] = candle(entry[-1]["time"], 1.103, open=1.1027, low=1.10265, high=1.10305)
    else:
        for i in range(-22, -2):
            entry[i] = candle(entry[i]["time"], 1.1005, open=1.1004, high=1.101, low=1.100)
        entry[-2] = candle(entry[-2]["time"], 1.1015, open=1.1008, high=1.1016, low=1.1007)
        entry[-1] = candle(entry[-1]["time"], 1.1015, open=1.1010, high=1.10155, low=1.10098)
    if side == "SELL":
        def reflect(rows):
            return [dict(time=r["time"], open=2.2-r["open"], close=2.2-r["close"],
                         high=2.2-r["low"], low=2.2-r["high"]) for r in rows]
        entry, macro = reflect(entry), reflect(macro)
    return entry, macro


@pytest.mark.parametrize("mode", sorted(HTF_MODES))
@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_closed_reclaim_and_confirmed_breakout_signals_are_symmetric(mode, side):
    entry, macro = pattern(mode, side)
    signal = detect_htf_signal(mode, entry, macro, buffer_price=.00003)
    assert signal is not None and signal.side == side
    assert signal.candle_time == entry[-1]["time"]
    assert not hasattr(signal, "risk_pct_override")  # Signals cannot alter protection or sizing.


@pytest.mark.parametrize("mode", sorted(HTF_MODES))
def test_signals_fail_closed_on_short_corrupt_future_or_opposite_context(mode):
    entry, macro = pattern(mode)
    assert detect_htf_signal(mode, entry[:149], macro, buffer_price=.00003) is None
    assert detect_htf_signal(mode, entry, macro[:149], buffer_price=.00003) is None
    corrupt = [dict(row) for row in entry]
    corrupt[-1]["close"] = float("nan")
    assert detect_htf_signal(mode, corrupt, macro, buffer_price=.00003) is None
    future = [dict(row) for row in macro]
    future[-1]["time"] = entry[-1]["time"]
    assert detect_htf_signal(mode, entry, future, buffer_price=.00003) is None
    _, opposite = pattern(mode, "SELL")
    assert detect_htf_signal(mode, entry, opposite, buffer_price=.00003) is None


def test_range_uses_prior_twenty_bars_and_requires_retest_confirmation():
    mode = "htf_range_retest"
    entry, macro = pattern(mode)
    signal = detect_htf_signal(mode, entry, macro, buffer_price=.00003)
    assert signal.level == pytest.approx(1.101)
    # Merely closing outside a range does not confirm a breakout without a retest.
    entry[-1] = candle(entry[-1]["time"], 1.102, open=1.1017, high=1.10205, low=1.10165)
    assert detect_htf_signal(mode, entry, macro, buffer_price=.00003) is None
    entry, macro = pattern(mode)
    entry[-2]["close"] = 1.1009
    assert detect_htf_signal(mode, entry, macro, buffer_price=.00003) is None


def test_trend_requires_pullback_and_reclaim_of_previous_high():
    mode = "htf_trend_pullback"
    entry, macro = pattern(mode)
    entry[-2] = candle(entry[-2]["time"], 1.10296)
    assert detect_htf_signal(mode, entry, macro, buffer_price=.00003) is None
    entry, macro = pattern(mode)
    entry[-2]["high"] = 1.1031
    assert detect_htf_signal(mode, entry, macro, buffer_price=.00003) is None


@pytest.mark.parametrize("mode", sorted(HTF_MODES))
def test_fixed_context_ignores_older_ema_initialization_data(mode):
    entry, macro = pattern(mode)
    expected = detect_htf_signal(mode, entry, macro, buffer_price=.00003)
    old = candle(entry[0]["time"]-3600, .8)
    old_macro = candle(macro[0]["time"]-14400, .8)
    assert detect_htf_signal(mode, [old]+entry, [old_macro]+macro, buffer_price=.00003) == expected


@pytest.fixture
def cfg(tmp_path):
    return models(load_config(Path("config/usdchf_m30_research_candidate.json")).symbols[0], "USDCHF")["htf_trend_pullback"]


@pytest.mark.parametrize("mode", sorted(HTF_MODES))
def test_live_and_replay_pass_identical_closed_h1_h4_bars(cfg, tmp_path, monkeypatch, mode):
    cfg = replace(cfg, strategy_mode=mode)
    entry, macro = pattern(mode)
    forming = candle(entry[-1]["time"]+3600, 9)
    macro_forming = candle(macro[-1]["time"]+14400, 9)
    captured = []
    def detect(mode, closed, bias, **kwargs):
        captured.append((mode, list(closed), list(bias), kwargs))
        return None
    monkeypatch.setattr(live, "detect_htf_signal", detect)
    monkeypatch.setattr(replay, "detect_htf_signal", detect)
    class Fake:
        pip_size = staticmethod(MT5Adapter.pip_size)
        def symbol_info(self, symbol):
            return NS(**SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001).__dict__)
        def copy_rates(self, symbol, timeframe, count):
            return entry+[forming] if timeframe == "H1" else macro+[macro_forming]
        def symbol_tick(self, symbol):
            raise AssertionError("No signal may reach execution")
    app = load_config(Path("config/usdchf_m30_research_candidate.json"))
    repo = SQLiteRepository(str(tmp_path / "state.db"))
    try:
        live.process_symbol(Fake(), cfg, app, live.SymbolState(), tmp_path / "events.csv", repo)
    finally:
        repo.close()
    replay._detect_signal_for_cfg(cfg, .0001, entry+[forming], [], macro)
    assert len(captured) == 2 and captured[0] == captured[1]
    assert captured[0][1] == entry and captured[0][2] == macro


def test_models_keep_all_risk_and_exit_settings_identical_on_each_pair():
    base = load_config(Path("config/usdchf_m30_research_candidate.json")).symbols[0]
    for symbol in ("EURUSD", "GBPUSD", "USDCHF"):
        variants = models(base, symbol)
        for cfg in variants.values():
            assert cfg.symbol == symbol
            assert all(getattr(cfg, key) == getattr(base, key) for key in PROTECTED)


@pytest.mark.parametrize("mode", sorted(HTF_MODES))
@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_offline_costed_replay_enters_from_closed_signals_and_ignores_future(cfg, monkeypatch, mode, side):
    def forbidden(*a, **k):
        raise AssertionError("Broker access or trading forbidden")
    monkeypatch.setattr(MT5Adapter, "initialize", forbidden)
    monkeypatch.setattr(MT5Adapter, "send_market_order_with_price_protection", forbidden)
    cfg = replace(cfg, strategy_mode=mode, allowed_sessions_utc=())
    app = load_config(Path("config/usdchf_m30_research_candidate.json"))
    entry, macro = pattern(mode, side)
    stamp = entry[-1]["time"]
    decision, finish = stamp+3600, stamp+5400
    micro = [candle(t, entry[-1]["close"]) for t in range(stamp-36000, finish+3600, 60)]
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)
    history = HistoricalData("USDCHF", info, {"M1": micro, "H1": entry, "H4": macro})
    _, trades = replay.run_backtest(app, cfg, datetime.fromtimestamp(stamp, timezone.utc),
        datetime.fromtimestamp(finish, timezone.utc), initial_equity=10000, costs=ExecutionCosts(),
        history=history, end_exclusive=True)
    assert len(trades) == 1 and trades[0].side == side
    assert trades[0].entry_time_utc == datetime.fromtimestamp(decision, timezone.utc).isoformat()
    assert trades[0].commission_cost_money > 0 and trades[0].slippage_cost_money > 0
    assert trades[0].spread_cost_money > 0 and trades[0].pnl_money < 0
    original = asdict(trades[0])
    history.rates["M1"][-1] = candle(micro[-1]["time"], 9)
    _, repeated = replay.run_backtest(app, cfg, datetime.fromtimestamp(stamp, timezone.utc),
        datetime.fromtimestamp(finish, timezone.utc), initial_equity=10000, costs=ExecutionCosts(),
        history=history, end_exclusive=True)
    assert asdict(repeated[0]) == original


@pytest.mark.parametrize("override", [{"timeframe": "M30"}, {"bias_timeframe": "H1"},
    {"confirmation_mode": "cisd"}, {"bias_lookback_bars": 100}, {"bars": 150},
    {"ema_fast_period": 50}])
def test_configuration_rejects_unsupported_contexts(cfg, tmp_path, override):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"symbols": [{**asdict(cfg), **override}]}))
    with pytest.raises(ValueError, match="H1/H4"):
        load_config(path)


def test_long_h4_context_warmup_covers_year_end_holidays_without_invented_bars(cfg):
    start = datetime(2026, 1, 15, tzinfo=timezone.utc)
    end = start+timedelta(hours=1)
    holidays = {"2025-12-24", "2025-12-25", "2025-12-26", "2025-12-31", "2026-01-01"}
    def native(step):
        rows = []
        cursor = start-timedelta(days=60)
        while cursor < end:
            if cursor.weekday() < 5 and cursor.date().isoformat() not in holidays:
                rows.append(candle(int(cursor.timestamp()), 1.1))
            cursor += timedelta(seconds=step)
        return rows
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)
    history = HistoricalData("USDCHF", info, {"M1": [candle(int(start.timestamp())+i*60, 1.1) for i in range(60)],
                                             "H1": native(3600), "H4": native(14400)})
    assert replay._max_buffer_days(cfg) >= 42
    assert history_coverage(history, cfg, start, end, max_gap_days=4) is None
