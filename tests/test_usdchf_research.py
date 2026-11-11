from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest

from src.backtesting.history import HistoricalData
from src.backtesting.costs import ExecutionCosts
from src.engine import orchestrator as live
from src.execution.mt5_adapter import MT5Adapter
from src.risk.sizing import SymbolTradeInfo
from src.services.config import AppConfig, load_config
from src.strategy.confirmations import ConfirmationResult
from src.strategy.liquidity import SweepSignal
from src.tools import backtest_mt5 as b
from src.tools.research_usdchf_m30 import candidates, select_training, select_fixed, promotion_checks, study_folds


@pytest.fixture
def app(tmp_path):
    base = load_config(tmp_path/"default.json")
    cfg = replace(base.symbols[0],symbol="USDCHF",timeframe="M30",cisd_timeframe="M5",
                  use_bias_filter=False,use_order_block_filter=False,allowed_sessions_utc=())
    return AppConfig(base.runtime,(cfg,))


@pytest.mark.parametrize("mode,expected", [("c3","M30"),("c4","M30"),("none","M30"),
                                          ("cisd","M5"),("sweep_displacement_mss","M5"),
                                          ("sweep_displacement_only","M5")])
def test_confirmation_timeframe_matches_live_config(app,mode,expected):
    assert b.confirmation_timeframe(replace(app.symbols[0],confirmation_mode=mode)) == expected


def test_live_and_backtest_confirmation_receive_identical_m5_bars(app,monkeypatch):
    cfg = app.symbols[0]
    closed = [dict(time=i*300,open=1.1,high=1.101,low=1.099,close=1.1005) for i in range(10)]
    expected = b._append_dummy_forming_bar(closed,300)
    seen=[]
    def evaluate(rates,*args,**kwargs):
        seen.append(list(rates))
        return ConfirmationResult(True,False,"confirmed")
    monkeypatch.setattr(live,"evaluate_sweep_displacement_mss_confirmation",evaluate)
    monkeypatch.setattr(b,"evaluate_sweep_displacement_mss_confirmation",evaluate)
    calls=[]
    def copy(symbol,timeframe,bars):
        calls.append(timeframe)
        return expected
    pending=NS(candle_time=0,side="BUY")
    live_result=live.evaluate_pending_confirmation(NS(copy_rates=copy),cfg,pending,[])
    replay_result=b._evaluate_confirmation(cfg,pending,closed)
    assert live_result == replay_result
    assert calls == ["M5"]
    assert seen[0] == seen[1]
    assert seen[1][-1]["time"]-seen[1][-2]["time"] == 300


def test_replay_uses_closed_m5_history_instead_of_m1_for_m30_pending_setup(app,monkeypatch):
    def forbidden(*a,**k):raise AssertionError("No broker access or trades")
    monkeypatch.setattr(MT5Adapter,"initialize",forbidden)
    monkeypatch.setattr(MT5Adapter,"send_market_order_with_price_protection",forbidden)
    cfg=replace(app.symbols[0],strategy_mode="trend_micro_burst_v2")
    app=AppConfig(app.runtime,(cfg,))
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    stamp=int(start.timestamp())
    rows=[dict(time=stamp+i*60,open=1.1,high=1.101,low=1.099,close=1.1,spread=10) for i in range(600)]
    info=SymbolTradeInfo(5,.00001,.01,100,.01,1,.00001)
    history=HistoricalData("USDCHF",info,{"M1":rows})
    monkeypatch.setattr(b,"_detect_signal_for_cfg",lambda cfg,pip,rates,*args:
                        (SweepSignal("BUY",1.0,rates[-2]["time"]),[],None))
    seen=[]
    def confirm(cfg,pending,closed):
        seen.append(closed)
        return ConfirmationResult(False,True,"waiting")
    monkeypatch.setattr(b,"_evaluate_confirmation",confirm)
    _,trades=b.run_backtest(app,cfg,start,start+timedelta(hours=10),initial_equity=10000,
                            costs=ExecutionCosts(),history=history,end_exclusive=True)
    assert not trades
    assert seen
    for bars in seen:
        assert len(bars)<=cfg.cisd_lookback_bars
        assert all(right["time"]-left["time"]==300 for left,right in zip(bars,bars[1:]))


def metrics(net=10,dd=5,trades=30):
    return {"net_pnl":net,"max_realized_drawdown":dd,"trades":trades}


def test_candidates_do_not_increase_risk_or_widen_initial_stop(app):
    base=app.symbols[0]
    variants=candidates(base)
    assert len(variants)==8
    for v in variants:
        for key in ("risk_pct","min_lot","max_lot","sl_pips","ignore_portfolio_cap"):
            assert getattr(v.settings,key)==getattr(base,key)
    assert next(v for v in variants if v.name=="fixed_2r").settings.trailing_stop_mode=="off"


def test_training_selection_rejects_small_samples_and_excess_drawdown():
    values={"baseline":metrics(),"good":metrics(20,6),"tiny":metrics(100,1,5),"risky":metrics(100,20)}
    assert select_training(values)=="good"
    assert select_training({"baseline":metrics(),"worse":metrics(9,6)})=="baseline"


def test_fixed_selection_cannot_use_confirmation_fold_results():
    training={i:{"baseline":metrics(),"good":metrics(20,6),"bad":metrics(1,5)} for i in range(1,13)}
    assert select_fixed(training)=="good"
    for i in (10,11,12):
        training[i]["good"]=metrics(-1000,1000)
        training[i]["bad"]=metrics(10000,0)
    assert select_fixed(training)=="good"


def test_more_training_history_does_not_move_or_overlap_test_windows():
    original,extended=study_folds(90),study_folds(365)
    assert len(original)==len(extended)==12
    for before,after in zip(original,extended):
        assert before.test_start==after.test_start
        assert before.test_end==after.test_end
        assert after.train_end==before.train_end
        assert after.train_end-after.train_start==timedelta(days=365)
        assert after.train_end < after.test_start


def test_six_fold_development_selection_never_reads_later_training_windows():
    training={i:{"baseline":metrics(),"good":metrics(20,6),"later":metrics(1,5)} for i in range(1,13)}
    for i in range(7,13):
        training[i]["later"]=metrics(100000,0)
    assert select_fixed(training,development_folds=6)=="good"


def test_promotion_fails_when_confirmation_or_stress_fails_even_if_total_profit_is_high():
    passing=promotion_checks(metrics(10),metrics(20),metrics(4),metrics(8),metrics(2),metrics(3),"good")
    assert all(passing.values())
    failed=promotion_checks(metrics(10),metrics(100),metrics(4),metrics(-1),metrics(2),metrics(-1),"good")
    assert not failed["holdout_net_positive_and_improved"]
    assert not failed["stress_net_positive_and_not_worse"]
