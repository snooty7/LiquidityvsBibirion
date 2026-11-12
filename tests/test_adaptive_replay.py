"""Integration checks on baseline replay hooks, frozen studies and reporting."""
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json

import pytest

from src.backtesting.adaptive_metrics import ledger_metrics
from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import HistoricalData, save_history
from src.risk.sizing import SymbolTradeInfo
from src.services.config import AppConfig, load_config
from src.strategy.liquidity import SweepSignal
from src.tools import backtest_mt5 as replay
from src.tools.research_adaptive import freeze, run_protocol


@pytest.fixture(autouse=True)
def no_broker(monkeypatch):
    from src.execution.mt5_adapter import MT5Adapter
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline study attempted broker access")
    for name in ("initialize", "send_market_order_with_price_protection", "send_market_order_with_fallback", "close_position_market_with_fallback", "modify_position_protection"):
        monkeypatch.setattr(MT5Adapter, name, forbidden)


def fixture(tmp_path):
    app = load_config(tmp_path/"default.json")
    cfg = replace(app.symbols[0], risk_pct=.1, max_lot=.1, strategy_mode="trend_micro_burst_v2",
                  confirmation_mode="none", allowed_sessions_utc=(), use_bias_filter=False,
                  use_order_block_filter=False, cooldown_sec=0, sl_pips=10, rr=2)
    app = AppConfig(replace(app.runtime, max_profit_per_trade_usd=0, trailing_stop_mode="off"), (cfg,))
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    stamp = int(start.timestamp())
    rows = [dict(time=stamp+i*60, open=1.1, high=1.1001, low=1.0999, close=1.1, spread=10) for i in range(150)]
    return app, cfg, HistoricalData("EURUSD", info, {"M1": rows}), start


def test_noop_policy_preserves_baseline_ledger_and_rejection_is_authoritative(tmp_path, monkeypatch):
    app, cfg, history, start = fixture(tmp_path)
    monkeypatch.setattr(replay, "_detect_signal_for_cfg", lambda cfg, pip, rates, *args: (SweepSignal("BUY", 1.0, rates[-2]["time"]), [], None))
    kwargs = dict(initial_equity=10000, costs=ExecutionCosts("fixed", 1, 3.5, .2), history=history, end_exclusive=True)
    end = start+timedelta(minutes=60)
    baseline, trades = replay.run_backtest(app, cfg, start, end, **kwargs)
    observed, repeated = replay.run_backtest(app, cfg, start, end, entry_policy=lambda **_: {}, **kwargs)
    assert trades and asdict(baseline) == asdict(observed)
    assert [asdict(item) for item in trades] == [asdict(item) for item in repeated]
    _, rejected = replay.run_backtest(app, cfg, start, end, entry_policy=lambda **_: None, **kwargs)
    assert rejected == []
    with pytest.raises(ValueError, match="offline history"):
        replay.run_backtest(app, cfg, start, end, initial_equity=10000, entry_policy=lambda **_: {})


def test_risk_sizing_remains_after_custom_protection(tmp_path, monkeypatch):
    app, cfg, history, start = fixture(tmp_path)
    cfg = replace(cfg, min_lot=.1, risk_pct=.01)
    monkeypatch.setattr(replay, "_detect_signal_for_cfg", lambda cfg, pip, rates, *args: (SweepSignal("BUY", 1.0, rates[-2]["time"]), [], None))
    _, trades = replay.run_backtest(app, cfg, start, start+timedelta(minutes=60), initial_equity=10000,
                                   costs=ExecutionCosts("fixed", 1, 3.5, .2), history=history, end_exclusive=True,
                                   entry_policy=lambda **_: {"sl_price": 1.09, "tp_price": 1.12})
    assert not trades  # The minimum lot cannot fit this much wider initial stop.


def test_frozen_protocol_detects_effective_config_drift_and_never_overwrites(tmp_path):
    app, cfg, history, start = fixture(tmp_path)
    config, data, protocol = (tmp_path/name for name in ("settings.json", "history.json", "protocol.json"))
    config.write_text(json.dumps({"symbols": [{"symbol": "EURUSD", "magic": cfg.magic}]}))
    save_history({"EURUSD": history}, data)
    options = dict(config=config, history=data, magic=cfg.magic, start="2026-01-05", end="2026-01-10",
                   output=protocol, train_days=1, validation_days=1, test_days=1, embargo_days=1,
                   equity=10000, costs=ExecutionCosts())
    freeze(**options)
    with pytest.raises(ValueError, match="already exist"):
        freeze(**options)
    config.with_name("settings.local.json").write_text(json.dumps({"runtime": {"daily_loss_limit_usd": 1}}))
    with pytest.raises(ValueError, match="Effective configuration changed"):
        run_protocol(protocol, tmp_path/"run")
    assert not (tmp_path/"run").exists()


def test_zero_sample_metrics_and_unavailable_comparison_are_honest(tmp_path):
    app, cfg, history, start = fixture(tmp_path)
    metrics = ledger_metrics([], 10000, start, start+timedelta(days=2))
    assert metrics["trades"] == 0 and metrics["win_rate_pct"] is None
    assert metrics["sharpe_realized_calendar_daily"] is None
    assert metrics["max_marked_equity_drawdown"] is None
    config, data, protocol = (tmp_path/name for name in ("settings.json", "history.json", "protocol.json"))
    config.write_text(json.dumps({"symbols": [{"symbol": "EURUSD", "magic": cfg.magic}]}))
    save_history({"EURUSD": history}, data)
    freeze(config=config, history=data, magic=cfg.magic, start="2026-01-05", end="2026-01-10", output=protocol,
           train_days=1, validation_days=1, test_days=1, embargo_days=1, equity=10000, costs=ExecutionCosts())
    report = run_protocol(protocol, tmp_path/"run")
    assert report["status"] == "partial_or_unavailable"
    assert report["shadow_ledger_invariant"] is None
    assert report["improvement_claim"] is False


def test_spread_stress_multiplies_observed_and_fallback_quotes():
    info = SymbolTradeInfo(5, .00001, .01, 100, .01, 1, .00001)
    costs = ExecutionCosts(spread_pips=1.5, spread_multiplier=2)
    assert costs.spread({"spread": 10}, info) == pytest.approx(2)
    assert costs.spread({}, info) == 3
    with pytest.raises(ValueError):
        ExecutionCosts(spread_multiplier=float("nan"))


def test_shadow_invariance_includes_a_nonempty_trade_ledger(tmp_path, monkeypatch):
    from src.backtesting.adaptive import AdaptiveReplayPolicy
    from src.strategy.adaptive.config import AdaptiveConfig
    from src.strategy.adaptive.models import (EntryProposal, Evaluation, Regime, RegimeResult,
                                               ScoreBreakdown, StructureContext)
    from src.backtesting import adaptive

    app, cfg, history, start = fixture(tmp_path)
    stamp = int(start.timestamp())
    history = HistoricalData("EURUSD", history.symbol_info, {
        "M1": [dict(time=stamp+(i-600)*60, open=1.1, high=1.1001, low=1.0999, close=1.1, spread=10)
               for i in range(750)],
        "H1": [dict(time=stamp+(i-110)*3600, open=1.1, high=1.1001, low=1.0999, close=1.1, spread=10)
               for i in range(112)]})
    config = AdaptiveConfig(enabled=True, context_timeframes=("H1",))
    regime = RegimeResult(Regime.TRENDING_BULLISH, .0001, 30, .5, .001, 1, "controlled_candidate")
    structure = StructureContext((), (), (1.103,), 1.099, 1.103)
    score = ScoreBreakdown(.9, (), (), ())

    def candidate(context, config, **kwargs):
        proposal = EntryProposal(str(context.decision_time), "EURUSD", "BUY", context.decision_time,
                                 kwargs["entry_price"], 1.099, 1.103, score, regime,
                                 (("H1", "BUY"),), structure, config.digest(), context.source_digest)
        return Evaluation(proposal, (), regime, score, (("H1", "BUY"),), structure)

    monkeypatch.setattr(adaptive, "evaluate", candidate)
    monkeypatch.setattr(replay, "_detect_signal_for_cfg", lambda cfg, pip, rates, *args: (SweepSignal("BUY", 1, rates[-2]["time"]), [], None))
    ledgers, observations = [], []
    for arm in ("adaptive", "adaptive_shadow"):
        policy = AdaptiveReplayPolicy(history, config, arm)
        _, trades = replay.run_backtest(app, cfg, start, start+timedelta(minutes=60), initial_equity=10000,
                                       costs=ExecutionCosts("fixed", 1, 3.5, .2), history=history,
                                       entry_policy=policy.entry, exit_policy=policy.exit, end_exclusive=True)
        ledgers.append([asdict(trade) for trade in trades])
        observations.append(policy.observations)
    assert ledgers[0] and ledgers[0] == ledgers[1]
    assert observations[0][0]["shadow"] is None
    assert observations[1][0]["shadow"]["status"] == "model_unavailable"
