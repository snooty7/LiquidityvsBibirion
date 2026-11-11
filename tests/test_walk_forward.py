"""All evaluation tests use synthetic bars and forbid broker/order access."""
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace as NS

import pytest

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import HistoricalData, load_history, resample_m1, save_history, validate_bars
from src.execution import mt5_adapter as mt5
from src.services.config import AppConfig, load_config
from src.tools import backtest_mt5 as b
from src.tools import walk_forward as w


@pytest.fixture(autouse=True)
def no_broker(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Broker connection or trading is forbidden in these tests")
    for method in ("initialize", "send_market_order_with_price_protection", "send_market_order_with_fallback",
                   "close_position_market_with_fallback", "modify_position_protection"):
        monkeypatch.setattr(mt5.MT5Adapter, method, forbidden)


@pytest.fixture
def cfg(tmp_path):
    app = load_config(tmp_path / "defaults.json")
    symbol = replace(app.symbols[0], risk_pct=1, max_lot=.1, strategy_mode="trend_micro_burst_v2",
                     confirmation_mode="none", allowed_sessions_utc=(), use_bias_filter=False,
                     use_order_block_filter=False, cooldown_sec=0, sl_pips=10, rr=2)
    runtime = replace(app.runtime, max_total_open_risk_pct=0, max_profit_per_trade_usd=0,
                      daily_loss_limit_usd=1000, trailing_stop_mode="off", push_notifications_enabled=False)
    return AppConfig(runtime, (symbol,))


@pytest.fixture
def info():
    from src.risk.sizing import SymbolTradeInfo
    return SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)


def bar(time, price=1.1, **kwargs):
    return dict(time=time, open=price, high=price+.00001, low=price-.00001,
                close=price, spread=10, tick_volume=100) | kwargs


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_round_trip_spread_commission_slippage_are_each_counted_once(cfg, info, side):
    costs = ExecutionCosts("fixed", 1, 3.5, .2)
    trade = b._build_entry_trade(cfg.symbols[0], cfg.runtime, info, 100000, side, 0, 1.1,
                                 "key", "test", costs=costs, spread_pips=1)
    assert trade is not None
    quote = costs.exit_quote(side, 1.1, 1, .0001)
    closed = b._close_trade(cfg.symbols[0], trade, 60, quote, "end_of_test", info, spread_pips=1)
    assert closed.volume == .1
    assert closed.spread_cost_money == pytest.approx(1)
    assert closed.commission_cost_money == pytest.approx(.7)
    assert closed.slippage_cost_money == pytest.approx(.4)
    assert closed.pnl_money == pytest.approx(-2.1)
    assert closed.gross_pnl_money == pytest.approx(0, abs=1e-9)
    assert closed.gross_pnl_money - closed.spread_cost_money - closed.commission_cost_money - closed.slippage_cost_money == pytest.approx(closed.pnl_money)


def test_historical_spread_is_points_and_zero_is_not_missing(info):
    costs = ExecutionCosts("historical", 2, 0, 0)
    assert costs.spread({"spread": 15}, info) == pytest.approx(1.5)
    assert costs.spread({"spread": 0}, info) == 0
    assert costs.spread({}, info) == 2
    assert ExecutionCosts("fixed", 2, 0, 0).spread({"spread": 100}, info) == 2
    jpy = replace(info, digits=3, point=.001, trade_tick_size=.001)
    assert costs.spread({"spread": 15}, jpy) == pytest.approx(1.5)


@pytest.mark.parametrize("values", [("bad", 1, 1, 1), ("fixed", -1, 0, 0),
                                    ("fixed", 1, float("nan"), 0), ("fixed", 1, 0, float("inf"))])
def test_invalid_costs_rejected(values):
    with pytest.raises(ValueError):
        ExecutionCosts(*values)


def test_short_stop_uses_ask_ohlc_and_stop_gap_is_adverse(cfg, info):
    costs = ExecutionCosts("fixed", 1, 0, .2)
    trade = b._build_entry_trade(cfg.symbols[0], cfg.runtime, info, 100000, "SELL", 0, 1.1,
                                 "key", "test", costs=costs, spread_pips=1)
    _, closed = b._apply_open_trade_bar(cfg.symbols[0], cfg.runtime, trade,
                                       bar(60, 1.1005, high=1.10095, low=1.1004, close=1.1006), info)
    assert closed is not None  # Bid high misses SL; ask high crosses it.
    assert closed.reason == "stop_loss"
    assert closed.exit_price == pytest.approx(trade.sl+.00002)
    buy = b._build_entry_trade(cfg.symbols[0], cfg.runtime, info, 100000, "BUY", 0, 1.1,
                               "key", "test", costs=costs, spread_pips=1)
    _, closed = b._apply_open_trade_bar(cfg.symbols[0], cfg.runtime, buy,
                                       bar(60, 1.0988, low=1.0987, high=1.099, close=1.0989), info)
    assert closed.exit_price == pytest.approx(1.0988-.00002)


def test_take_profit_limit_has_no_exit_slippage(cfg, info):
    costs = ExecutionCosts("fixed", 1, 0, .2)
    trade = b._build_entry_trade(cfg.symbols[0], cfg.runtime, info, 100000, "BUY", 0, 1.1,
                                 "key", "test", costs=costs, spread_pips=1)
    _, closed = b._apply_open_trade_bar(cfg.symbols[0], cfg.runtime, trade,
                                       bar(60, trade.tp+.0001), info)
    assert closed.reason == "take_profit"
    assert closed.exit_price == trade.tp
    assert closed.slippage_cost_money == pytest.approx(.2)


def test_offline_replay_applies_costs_and_excludes_future_prices(cfg, info, monkeypatch):
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    stamp = int(start.timestamp())
    rows = [bar(stamp+i*60) for i in range(100)]
    history = HistoricalData("EURUSD", info, {"M1": rows})
    calls = []
    from src.strategy.liquidity import SweepSignal
    def signal(cfg, pip, rates, *args):
        calls.append(rates[-2]["time"])
        return SweepSignal("BUY", 1.0, rates[-2]["time"]), [], None
    monkeypatch.setattr(b, "_detect_signal_for_cfg", signal)
    end = start+timedelta(minutes=60)
    costs = ExecutionCosts("fixed", 1, 3.5, .2)
    result, trades = b.run_backtest(cfg, cfg.symbols[0], start, end, initial_equity=100000,
                                     costs=costs, history=history, end_exclusive=True)
    assert len(trades) == 1
    assert trades[0].pnl_money == pytest.approx(-2.1)
    assert trades[0].exit_time_utc == end.isoformat()
    assert result.ending_equity == pytest.approx(99997.9)
    assert all(datetime.fromtimestamp(t, timezone.utc) < end for t in calls)
    original = asdict(trades[0])
    # A later spike must never affect earlier train/test results.
    history.rates["M1"][-1] = bar(stamp+99*60, 9)
    _, repeated = b.run_backtest(cfg, cfg.symbols[0], start, end, initial_equity=100000,
                                costs=costs, history=history, end_exclusive=True)
    assert asdict(repeated[0]) == original


def test_resampling_discards_gaps_and_incomplete_forming_bars():
    rows = [bar(i*60, 1.1+i*.0001) for i in range(12)]
    result = resample_m1(rows, "M5")
    assert [row["time"] for row in result] == [0, 300]
    assert result[0]["close"] == rows[4]["close"]
    assert result[0]["tick_volume"] == 500
    assert [row["time"] for row in resample_m1(rows[:2]+rows[3:], "M5")] == [300]


@pytest.mark.parametrize("rows", [[bar(60), bar(60)], [bar(61)], [bar(0, high=1.0)],
                                  [bar(0, spread=-1)], [bar(0, close=float("nan"))]])
def test_invalid_history_rejected(rows):
    with pytest.raises(ValueError):
        validate_bars(rows, "M1")


def test_history_round_trip_and_fingerprint_include_supplied_timeframes(tmp_path, info):
    original = HistoricalData("EURUSD", info, {"M1": [bar(i*60) for i in range(15)]})
    digest = original.digest()
    original.bars("M5")
    assert original.digest() == digest
    path = tmp_path/"history.json"
    save_history({"EURUSD": original}, path)
    loaded = load_history(path)["EURUSD"]
    assert loaded.digest() == digest
    supplied = HistoricalData("EURUSD", info, {"M1": loaded.rates["M1"], "M5": [bar(0)]})
    assert supplied.digest() != digest
    native_path = tmp_path/"native.json"
    save_history({"EURUSD": supplied}, native_path)
    native = load_history(native_path)["EURUSD"]
    assert native.rates["M5"] == supplied.rates["M5"]
    assert native.digest() == supplied.digest()
    doc = json.loads(path.read_text())
    doc["quote_basis"] = "mid"
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="quote_basis"):
        load_history(path)


def test_folds_are_chronological_nonoverlapping_and_embargoed():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    folds = w.make_folds(start, start+timedelta(days=181), 90, 30, 1)
    assert len(folds) == 3
    assert folds[0].train_start == start
    for fold in folds:
        assert fold.train_end+timedelta(days=1) == fold.test_start
        assert fold.test_start+timedelta(days=30) == fold.test_end
    assert folds[0].test_end == folds[1].test_start
    with pytest.raises(ValueError):
        w.make_folds(start, start+timedelta(days=100))


def make_trade(start, end, net):
    return b.ClosedTrade("EURUSD", "BUY", (start+timedelta(hours=1)).isoformat(),
                         (end-timedelta(hours=1)).isoformat(), 1.1, 1.1, 1, 2, 1, 2,
                         .1, net, net/10, "test", "ok", "key", gross_pnl_money=net)


def branches(cfg):
    return [w.Branch("A", cfg, cfg.symbols[0], "A"),
            w.Branch("B", AppConfig(cfg.runtime, (replace(cfg.symbols[0], magic=999),)),
                     replace(cfg.symbols[0], magic=999), "B")]


@pytest.mark.parametrize("oos_a,oos_b", [(100, -100), (-100, 100)])
def test_selection_uses_training_only_not_test_performance(cfg, info, monkeypatch, oos_a, oos_b):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    folds = w.make_folds(start, start+timedelta(days=3), 1, 1, 0)
    monkeypatch.setattr(w, "history_coverage", lambda *args, **kwargs: None)
    history = HistoricalData("EURUSD", info, {"M1": [bar(0)]})
    def runner(app, symbol, begin, end, **kwargs):
        is_a = symbol.magic != 999
        training = begin == folds[0].train_start
        net = (5 if is_a else 10) if training else (oos_a if is_a else oos_b)
        return NS(skipped_risk=0), [make_trade(begin, end, net)]
    result = w.evaluate(branches(cfg), {"EURUSD": history}, [folds[0]],
                        ExecutionCosts(), min_train_trades=1, runner=runner)
    assert result["selections"][0]["selected_branch"] == "B"
    assert result["selected_oos"]["net_pnl"] == oos_b


def test_no_eligible_branch_holds_cash_and_missing_test_is_incomplete(cfg, info, monkeypatch):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    fold = w.make_folds(start, start+timedelta(days=2), 1, 1, 0)[0]
    history = HistoricalData("EURUSD", info, {"M1": [bar(0)]})
    monkeypatch.setattr(w, "history_coverage", lambda *args, **kwargs: None)
    def runner(app, symbol, begin, end, **kwargs):
        return NS(skipped_risk=0), [make_trade(begin, end, 1)]
    result = w.evaluate(branches(cfg), {"EURUSD": history}, [fold], ExecutionCosts(), runner=runner)
    assert result["selections"][0]["selected_branch"] is None
    assert result["selected_oos"]["trades"] == 0
    monkeypatch.setattr(w, "history_coverage", lambda history, cfg, begin, end, **kwargs:
                        "missing test" if begin == fold.test_start else None)
    result = w.evaluate(branches(cfg), {"EURUSD": history}, [fold], ExecutionCosts(),
                        min_train_trades=1, runner=runner)
    assert result["selections"][0]["selected_branch"] == "A"
    assert result["selected_oos_complete"] is False
    assert result["summaries"][0]["successful_test_folds"] == 0
    assert result["summaries"][0]["metrics"] is None


def test_missing_training_data_cannot_select_a_surviving_branch(cfg, info, monkeypatch):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    fold = w.make_folds(start, start+timedelta(days=2), 1, 1, 0)[0]
    history = HistoricalData("EURUSD", info, {"M1": [bar(0)]})
    monkeypatch.setattr(w, "history_coverage", lambda history, symbol, begin, end, **kwargs:
                        "missing" if symbol.magic == 999 and begin == fold.train_start else None)
    def runner(app, symbol, begin, end, **kwargs):
        return NS(skipped_risk=0), [make_trade(begin, end, 10)]
    result = w.evaluate(branches(cfg), {"EURUSD": history}, [fold], ExecutionCosts(),
                        min_train_trades=1, runner=runner)
    assert result["selections"][0]["selected_branch"] is None
    assert not result["selections"][0]["training_complete"]
    assert not result["selected_oos_complete"]


def test_evaluator_rejects_overlapping_test_windows(cfg):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    fold = w.make_folds(start, start+timedelta(days=2), 1, 1, 0)[0]
    with pytest.raises(ValueError, match="Overlapping"):
        w.evaluate(branches(cfg), {}, [fold, fold], ExecutionCosts())


def test_default_cli_writes_inventory_without_broker_access(tmp_path, monkeypatch):
    config = tmp_path / "settings.json"
    config.write_text(json.dumps({"symbols": [{"symbol": "EURUSD"}]}), encoding="utf-8-sig")
    import sys
    monkeypatch.setattr(sys, "argv", ["walk_forward", "--configs", str(config), "--output", str(tmp_path/"report")])
    w.main()
    assert json.loads((tmp_path/"report"/"report.json").read_text())["status"] == "awaiting_history"


def test_default_discovery_includes_crypto_research_but_excludes_templates_and_overrides(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    for name in ("settings.json", "btc_research.json", "settings.example.json", "settings.local.json"):
        (config / name).write_text("{}")
    live = tmp_path / "live" / "demo"
    live.mkdir(parents=True)
    (live / "settings.json").write_text("{}")
    found = w.default_config_paths(tmp_path)
    assert config / "btc_research.json" in found
    assert live / "settings.json" in found
    assert len(found) == 3


def test_report_renders_unavailable_metrics_without_crashing(cfg, tmp_path):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    fold = w.make_folds(start, start+timedelta(days=2), 1, 1, 0)[0]
    source = branches(cfg)
    evaluation = w.evaluate(source, {}, [fold], ExecutionCosts())
    doc = w.report_document(source, ExecutionCosts(), {}, evaluation)
    _, path = w.write_report(doc, tmp_path)
    assert "unavailable" in path.read_text()
    assert doc["status"] == "partial_or_unavailable"


def test_report_is_strict_json_escapes_html_and_does_not_invent_metrics(cfg, tmp_path):
    source = branches(cfg)
    source[0].sources = ["<script>alert(1)</script>"]
    doc = w.report_document(source, ExecutionCosts(), {})
    json_path, html_path = w.write_report(doc, tmp_path)
    parsed = json.loads(json_path.read_text())
    assert parsed["status"] == "awaiting_history"
    assert parsed["evaluation"] is None
    assert "<script>" not in html_path.read_text()
    assert "&lt;script&gt;" in html_path.read_text()
    assert "push_notification" not in json_path.read_text()


def test_profile_discovery_handles_bom_and_deduplicates_only_identical_behavior(tmp_path):
    first, second = tmp_path/"a.json", tmp_path/"b.json"
    doc = {"runtime": {"push_notification_token": "SECRET"},
           "symbols": [{"symbol": "EURUSD", "magic": 123, "risk_pct": .1}]}
    first.write_text(json.dumps(doc), encoding="utf-8-sig")
    second.write_text(json.dumps(doc))
    found = w.discover_branches([first, second])
    assert len(found) == 1
    assert len(found[0].sources) == 2
    assert found[0].config.runtime.dry_run
    assert not found[0].config.runtime.push_notifications_enabled
    doc["symbols"][0]["risk_pct"] = .2
    second.write_text(json.dumps(doc))
    assert len(w.discover_branches([first, second])) == 2


def test_missing_warmup_or_long_gaps_prevents_misleading_fold(cfg, info):
    start = datetime(2025, 1, 10, tzinfo=timezone.utc)
    stamp = int(start.timestamp())
    history = HistoricalData("EURUSD", info, {"M1": [bar(stamp+i*60) for i in range(15)]})
    assert "warm-up" in w.history_coverage(history, cfg.symbols[0], start, start+timedelta(minutes=15))
    history.rates["M1"].insert(0, bar(stamp-30*86400))
    assert "gap" in w.history_coverage(history, cfg.symbols[0], start, start+timedelta(days=5))


def test_an_old_isolated_bar_is_not_sufficient_indicator_warmup(cfg, info):
    start = datetime(2025, 1, 10, tzinfo=timezone.utc)
    stamp = int(start.timestamp())
    rows = [bar(stamp-30*86400), *[bar(stamp+i*60) for i in range(15)]]
    history = HistoricalData("EURUSD", info, {"M1": rows})
    assert "warm-up bars" in w.history_coverage(history, cfg.symbols[0], start, start+timedelta(minutes=15))


def test_warmup_counts_actual_bars_instead_of_requiring_a_tick_at_calendar_anchor(cfg, info):
    start = datetime(2025, 1, 13, tzinfo=timezone.utc)
    stamp = int(start.timestamp())
    symbol = replace(cfg.symbols[0], timeframe="M1", bars=10)
    rows = [bar(stamp-3*86400+i*60) for i in range(10)]
    rows += [bar(stamp+i*60) for i in range(15)]
    history = HistoricalData("EURUSD", info, {"M1": rows})
    assert w.history_coverage(history, symbol, start, start+timedelta(minutes=15)) is None


def test_explicit_gap_tolerance_can_accommodate_market_holiday_without_inventing_bars(cfg, info):
    start = datetime(2026, 4, 2, tzinfo=timezone.utc)
    stamp = int(start.timestamp())
    symbol = replace(cfg.symbols[0], timeframe="M1", bars=10)
    rows = [bar(stamp-60*(10-i)) for i in range(10)]
    rows += [bar(stamp+i*60) for i in range(15)]
    rows += [bar(stamp+3*86400+20*60+i*60) for i in range(15)]
    history = HistoricalData("EURUSD", info, {"M1": rows})
    end = start+timedelta(days=3,hours=1)
    assert "data gap" in w.history_coverage(history,symbol,start,end)
    assert w.history_coverage(history,symbol,start,end,max_gap_days=4) is None
    assert len(history.rates["M1"]) == len(rows)


def test_out_of_window_outcomes_are_rejected_instead_of_leaking_into_selection(cfg, info, monkeypatch):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    fold = w.make_folds(start, start+timedelta(days=2), 1, 1, 0)[0]
    monkeypatch.setattr(w, "history_coverage", lambda *args, **kwargs: None)
    def runner(app, symbol, begin, end, **kwargs):
        trade = make_trade(begin, end, 1000)
        trade.exit_time_utc = (end+timedelta(seconds=1)).isoformat()
        return NS(skipped_risk=0), [trade]
    result = w.evaluate(branches(cfg), {"EURUSD": HistoricalData("EURUSD", info, {"M1": [bar(0)]})},
                        [fold], ExecutionCosts(), min_train_trades=1, runner=runner)
    assert all(row["status"] == "error" for row in result["rows"])
    assert result["selections"][0]["selected_branch"] is None
    assert not result["selected_oos_complete"]


def test_drawdown_counts_entry_cost_and_aggregate_costs_reconcile():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    trade = make_trade(start, start+timedelta(days=1), 10)
    trade.commission_cost_money = 4
    trade.gross_pnl_money = 17
    trade.spread_cost_money = 2
    trade.slippage_cost_money = 1
    metrics = w.trade_metrics([trade], 1000)
    assert metrics["max_realized_drawdown"] == 2
    assert metrics["gross_pnl"]-metrics["spread_cost"]-metrics["commission_cost"]-metrics["slippage_cost"] == metrics["net_pnl"]
    assert metrics["profit_factor"] is None
