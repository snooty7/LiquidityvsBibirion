from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import HistoricalData
from src.engine import orchestrator as live
from src.execution.mt5_adapter import MT5Adapter
from src.persistence.repository import SQLiteRepository
from src.persistence.recovery import build_pending_setup_record
from src.risk.sizing import SymbolTradeInfo
from src.services.config import AppConfig,load_config
from src.strategy import filters
from src.strategy.confirmations import ConfirmationResult
from src.strategy.liquidity import SweepSignal
from src.tools import backtest_mt5 as b
from src.tools import research_long_filter as study
from src.tools.walk_forward import discover_branches


def bars(count=80,slope=.0001,start=0,step=14400):
    return [dict(time=start+i*step,open=1+i*slope,close=1+i*slope,
                 high=1+i*slope+.0002,low=1+i*slope-.0002) for i in range(count)]


@pytest.fixture
def app(tmp_path):
    cfg=load_config(tmp_path/"defaults.json")
    symbol=replace(cfg.symbols[0],symbol="USDCHF",timeframe="M30",cisd_timeframe="M1",
                   cisd_lookback_bars=300,bias_timeframe="H4",allowed_sessions_utc=(),
                   use_order_block_filter=False,long_entry_filter_mode="ema_slope_atr",
                   long_entry_min_slope_atr=100)
    return AppConfig(replace(cfg.runtime,dry_run=True,push_notifications_enabled=False),(symbol,))


@pytest.fixture
def info():
    return SymbolTradeInfo(5,.00001,.01,100,.01,1,.00001)


def test_feature_is_scale_invariant_and_fixed_context():
    rates=bars()
    value=filters.long_entry_slope_atr(rates)
    scaled=[dict(row,**{k:row[k]*10 for k in ("open","high","low","close")}) for row in rates]
    assert filters.long_entry_slope_atr(scaled)==pytest.approx(value)
    assert filters.long_entry_slope_atr(bars(20,start=-20*14400)+rates)==value
    assert filters.long_entry_slope_atr(bars(slope=.00001))<value


def test_gate_uses_inclusive_threshold_and_fails_closed_for_unavailable_context():
    rates=bars();value=filters.long_entry_slope_atr(rates)
    assert filters.evaluate_long_entry_filter("BUY",rates,mode="ema_slope_atr",min_slope_atr=value).allowed
    assert not filters.evaluate_long_entry_filter("BUY",rates,mode="ema_slope_atr",min_slope_atr=value+.001).allowed
    assert not filters.evaluate_long_entry_filter("BUY",rates[:5],mode="ema_slope_atr").allowed
    broken=[dict(row,high=float("nan")) for row in rates]
    assert not filters.evaluate_long_entry_filter("BUY",broken,mode="ema_slope_atr").allowed


def test_sell_and_disabled_gate_do_not_read_long_features(monkeypatch):
    def forbidden(*a,**k):raise AssertionError("feature should not be read")
    monkeypatch.setattr(filters,"long_entry_slope_atr",forbidden)
    assert filters.evaluate_long_entry_filter("SELL",[],mode="ema_slope_atr",min_slope_atr=100).allowed
    assert filters.evaluate_long_entry_filter("BUY",[],mode="off").allowed


def test_feature_at_excludes_forming_and_future_h4_candles(app,info):
    rates=bars()
    history=HistoricalData("USDCHF",info,{"M1":[],"H4":rates.copy()})
    timestamp=80*14400
    before=study.feature_at(history,app.symbols[0],timestamp)
    history.rates["H4"].extend(bars(10,slope=.1,start=timestamp))
    history._time_index.clear()
    assert study.feature_at(history,app.symbols[0],timestamp)==before
    assert study.feature_at(history,app.symbols[0],timestamp-1) is None


def test_quantiles_use_feature_distribution_without_profit_labels_or_sell_entries(monkeypatch,app):
    start=datetime(2025,1,1,tzinfo=timezone.utc);end=start+timedelta(days=1)
    trades=[NS(side="BUY",entry_time_utc=(start+timedelta(minutes=i)).isoformat(),
               exit_time_utc=(start+timedelta(hours=1)).isoformat(),pnl_money=-100) for i in range(20)]
    monkeypatch.setattr(study,"feature_at",lambda h,cfg,t:(t-int(start.timestamp()))/60)
    first=study.fit_thresholds(None,app.symbols[0],trades,start,end)
    for t in trades:t.pnl_money=10000
    trades.append(NS(side="SELL",entry_time_utc=start.isoformat(),exit_time_utc=end.isoformat()))
    assert study.fit_thresholds(None,app.symbols[0],trades,start,end)==first
    assert first["thresholds"]=={"q25":4.75,"q50":9.5}
    assert study.fit_thresholds(None,app.symbols[0],trades[:19],start,end)["thresholds"]=={}
    with pytest.raises(ValueError,match="contained"):
        study.fit_thresholds(None,app.symbols[0],trades,start+timedelta(hours=2),end)


def record(net=10,dd=5,buy_net=2,buy_trades=25):
    return {"metrics":{"net_pnl":net,"max_realized_drawdown":dd},
            "buy_metrics":{"net_pnl":buy_net,"trades":buy_trades}}


def test_selection_maximizes_profit_subject_to_unchanged_constraints():
    values={"off":record(),"q25":record(20,5),"q50":record(25,6)}
    assert study.select_profit(values)[0]=="q50"
    values["q50"]=record(30,6.3)
    assert study.select_profit(values)[0]=="q25"
    values["q25"]=record(40,5,buy_trades=19)
    assert study.select_profit(values)[0]=="off"
    assert study.select_profit({"off":record(),"q25":record(50,5,buy_net=-1)})[0]=="off"


@pytest.mark.parametrize("settings",[{"long_entry_filter_mode":"unknown"},
    {"long_entry_min_slope_atr":-1},{"long_entry_min_slope_atr":float("nan")},
    {"long_entry_slope_bars":0},{"long_entry_atr_period":1}])
def test_config_rejects_invalid_long_filter_parameters(tmp_path,settings):
    p=tmp_path/"settings.json";p.write_text(json.dumps({"symbols":[{"symbol":"USDCHF",**settings}]}))
    with pytest.raises(ValueError):load_config(p)


def test_disabled_filter_preserves_branch_identity(tmp_path):
    p=tmp_path/"settings.json"
    p.write_text(json.dumps({"symbols":[{"symbol":"USDCHF"}]}))
    before=discover_branches([p])[0].fingerprint
    p.write_text(json.dumps({"symbols":[{"symbol":"USDCHF","long_entry_filter_mode":"off",
                                        "long_entry_min_slope_atr":10}]}))
    assert discover_branches([p])[0].fingerprint==before
    p.write_text(json.dumps({"symbols":[{"symbol":"USDCHF","long_entry_filter_mode":"ema_slope_atr",
                                        "long_entry_min_slope_atr":10}]}))
    assert discover_branches([p])[0].fingerprint!=before


def test_build_entry_cannot_bypass_enabled_buy_filter_but_sell_rule_is_unchanged(app,info):
    cfg=app.symbols[0]
    args=(cfg,app.runtime,info,10000)
    assert b._build_entry_trade(*args,"BUY",100,1.1,"key","ok") is None
    assert b._build_entry_trade(*args,"SELL",100,1.1,"key","ok") is not None


def test_live_entry_uses_closed_canonical_bias_and_shared_long_gate(app,info,tmp_path,monkeypatch):
    cfg=app.symbols[0]
    macro=bars();forming=dict(macro[-1],time=80*14400,close=100,high=100)
    requests=[];seen=[]
    class Fake:
        pip_size=staticmethod(MT5Adapter.pip_size)
        def symbol_info(self,symbol):return NS(**info.__dict__)
        def copy_rates(self,symbol,tf,count):
            requests.append((tf,count))
            return macro+[forming] if tf=="H4" else bars(3,start=0,step=1800)
        def spread_pips(self,*args):return .5
        def positions_get(self,*args,**kwargs):return []
        def symbol_tick(self,*args):raise AssertionError("Rejected BUY must not reach quote/execution")
    monkeypatch.setattr(live,"detect_sweep_signal",lambda *args:None)
    monkeypatch.setattr(live,"evaluate_pending_confirmation",lambda *args:ConfirmationResult(True,False,"confirmed"))
    def bias(rates,period):
        seen.append(list(rates));return {"ok_buy":True,"ok_sell":True,"note":"ok"}
    monkeypatch.setattr(live,"evaluate_bias",bias)
    repo=SQLiteRepository(str(tmp_path/"state.db"))
    try:
        record=build_pending_setup_record(symbol="USDCHF",timeframe="M30",side="BUY",level=1.0,
            candle_time=0,signal_key="BUY|1",expires_at=10000,context={},initial_status="PENDING")
        stored,_=repo.create_or_get_pending_setup(record)
        live.process_symbol(Fake(),cfg,app,live.SymbolState(pending_setup=live.pending_from_record(stored)),
                            tmp_path/"events.csv",repo)
        assert ("H4",81) in requests
        assert seen==[macro]
        assert "SKIP_LONG_FILTER" in (tmp_path/"events.csv").read_text()
        assert b.entry_long_filter(cfg,"BUY",macro)==filters.evaluate_long_entry_filter(
            "BUY",macro,mode=cfg.long_entry_filter_mode,min_slope_atr=cfg.long_entry_min_slope_atr)
    finally:repo.close()


def test_replay_rejects_filtered_buy_before_any_order_and_uses_same_bias_count(app,info,monkeypatch):
    cfg=replace(app.symbols[0],strategy_mode="trend_micro_burst_v2")
    app=AppConfig(app.runtime,(cfg,))
    start=datetime(2026,1,1,tzinfo=timezone.utc);stamp=int(start.timestamp())
    micro=bars(600,start=stamp,step=60,slope=.000001)
    macro=bars(120,start=stamp-120*14400)
    history=HistoricalData("USDCHF",info,{"M1":micro,"H4":macro})
    def forbidden(*a,**k):raise AssertionError("Broker calls forbidden")
    monkeypatch.setattr(MT5Adapter,"initialize",forbidden)
    monkeypatch.setattr(MT5Adapter,"send_market_order_with_price_protection",forbidden)
    monkeypatch.setattr(b,"_detect_signal_for_cfg",lambda cfg,pip,rates,*a:(SweepSignal("BUY",1.0,rates[-2]["time"]),[],None))
    monkeypatch.setattr(b,"_evaluate_confirmation",lambda *a:ConfirmationResult(True,False,"confirmed"))
    seen=[]
    def bias(rates,period):
        seen.append(rates);return {"ok_buy":True,"ok_sell":True,"note":"ok"}
    monkeypatch.setattr(b,"evaluate_bias",bias)
    result,trades=b.run_backtest(app,cfg,start,start+timedelta(hours=10),initial_equity=10000,
                                 costs=ExecutionCosts(),history=history,end_exclusive=True)
    assert not trades and result.skipped_long_filter>0
    assert seen and all(len(rates)==80 for rates in seen)
