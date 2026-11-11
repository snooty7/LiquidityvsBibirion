"""Profit-first, training-derived BUY eligibility study. Saved history only; trading is blocked."""
from __future__ import annotations

import argparse
import bisect
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import HistoricalData, TIMEFRAMES, load_history
from src.services.config import SymbolConfig
from src.strategy.filters import long_entry_context_count, long_entry_slope_atr
from src.tools.backtest_mt5 import ClosedTrade
from src.tools.research_usdchf_m30 import _forbid_broker, _initialize_worker, _replay, study_folds
from src.tools.walk_forward import RISK_KEYS, default_config_paths, discover_branches, trade_metrics


def quantile(values: list[float], probability: float) -> float:
    """Linearly interpolated quantile, fitted on training feature values only."""
    if not values or not 0 <= probability <= 1 or not all(math.isfinite(v) for v in values):
        raise ValueError("A quantile requires finite observations and probability in [0,1]")
    ordered = sorted(values)
    position = (len(ordered)-1)*probability
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower]+(ordered[upper]-ordered[lower])*(position-lower)


def feature_at(history: HistoricalData, cfg: SymbolConfig, timestamp: int) -> float | None:
    """Use only higher-timeframe bars closed at the entry decision timestamp."""
    timeframe = cfg.bias_timeframe
    end = bisect.bisect_right(history.timestamps(timeframe),timestamp-TIMEFRAMES[timeframe])
    count = long_entry_context_count(cfg.bias_ema_period,cfg.long_entry_atr_period,cfg.long_entry_slope_bars)
    return long_entry_slope_atr(history.bars(timeframe)[max(0,end-count):end],
        ema_period=cfg.bias_ema_period,atr_period=cfg.long_entry_atr_period,slope_bars=cfg.long_entry_slope_bars)


def fit_thresholds(history: HistoricalData, cfg: SymbolConfig, trades: list[ClosedTrade],
                   start: datetime, end: datetime) -> dict:
    """Fit Q25/Q50 from all observable training BUY entries, without winner labels."""
    values = []
    for trade in trades:
        entry = datetime.fromisoformat(trade.entry_time_utc)
        exit_time = datetime.fromisoformat(trade.exit_time_utc)
        if not start <= entry < end or not entry <= exit_time <= end:
            raise ValueError("Training trades must be contained in the fitting window")
        if trade.side == "BUY":
            feature = feature_at(history,cfg,int(entry.timestamp()))
            if feature is not None and math.isfinite(feature):
                values.append(feature)
    return {"buy_observations":len(values),"thresholds":{
        "q25":max(0.0,quantile(values,.25)), "q50":max(0.0,quantile(values,.50))
    } if len(values) >= 20 else {}}


def select_profit(training: dict[str, dict]) -> tuple[str, dict[str, list[str]]]:
    """Maximize net profit with fixed sample/drawdown constraints and an unfiltered fallback."""
    baseline = training["off"]["metrics"]
    rejected, eligible = {}, []
    for name, record in training.items():
        if name == "off":
            continue
        total, buys = record["metrics"], record["buy_metrics"]
        failures = []
        if buys["trades"] < 20: failures.append("fewer than 20 retained training BUY trades")
        if buys["net_pnl"] <= 0: failures.append("training BUY net not positive")
        if total["net_pnl"] <= max(0.0,baseline["net_pnl"]): failures.append("training total net not positive and improved")
        if total["max_realized_drawdown"] > 1.25*baseline["max_realized_drawdown"]:
            failures.append("training drawdown exceeds 1.25 baseline")
        rejected[name] = failures
        if not failures:
            eligible.append((name,total["net_pnl"],total["max_realized_drawdown"]))
    eligible.sort(key=lambda row:(-row[1],row[2],row[0]))
    return eligible[0][0] if eligible else "off", rejected


def side_metrics(trades: list[ClosedTrade]) -> dict:
    return {side:trade_metrics([trade for trade in trades if trade.side==side],10000) for side in ("BUY","SELL")}


def run(history_path: Path, output: Path, workers: int = 6) -> dict:
    """Register, fit training thresholds, select for profit, lock, then replay and stress tests."""
    _forbid_broker()
    source = next(b for b in discover_branches(default_config_paths())
                  if b.branch_id=="92024-USDCHF-M30-3c27c3d9")
    base = replace(source.symbol,cisd_timeframe="M1",cisd_lookback_bars=300,
                   long_entry_filter_mode="off",long_entry_min_slope_atr=0.0)
    history = load_history(history_path)["USDCHF"]
    history_hash = history.digest()
    costs, stress = ExecutionCosts(), ExecutionCosts("historical",2.0,7.0,.4)
    folds = study_folds(365)
    code_hash = hashlib.sha256(b"".join(path.read_bytes() for folder in (
        "src/strategy","src/risk","src/backtesting","src/engine"
    ) for path in sorted(Path(folder).glob("*.py")))+Path("src/tools/backtest_mt5.py").read_bytes()
        +Path("src/services/config.py").read_bytes()+Path(__file__).read_bytes()).hexdigest()
    output.mkdir(parents=True,exist_ok=True)
    cache = history_path.parent/"long_filter_cache"
    cache.mkdir(exist_ok=True)
    plan = {
        "registered_at_utc":datetime.now(timezone.utc).isoformat(),
        "objective":"maximize training net profit after costs; drawdown and sample constraints unchanged",
        "hypotheses":["off","training BUY-feature Q25","training BUY-feature Q50"],
        "feature":"EMA20 rise over 3 closed H4 bars / mean true range of last 14 closed H4 bars, fixed 80-bar EMA initialization",
        "fit_rule":"nonnegative Q25/Q50 from all training baseline BUY entries; at least 20 feature observations; no outcome labels in quantile fitting",
        "select_rule":"highest total net among positive/improved total net, positive BUY net, >=20 retained BUY trades, DD<=1.25 baseline; otherwise off",
        "folds":[f.record() for f in folds],"confirmation_folds":[7,8,9,10,11,12],
        "costs":asdict(costs),"stress_costs":asdict(stress),
        "baseline_settings":asdict(base),"risk_runtime":{key:getattr(source.config.runtime,key) for key in RISK_KEYS},
        "history_sha256":history_hash,"replay_code_sha256":code_hash,
        "risk_unchanged":["0.1% risk","20-pip initial stop","0.05 max lot","one position","daily/exposure guards","trailing rules"],
        "promotion_gates":"filter selected in >=1 fold; improved aggregate and positive/improved confirmation net; >=20 confirmation trades; aggregate/confirmation DD<=1.25 baseline; positive/not-worse stress confirmation",
        "engine_alignment":"Entry-bias EMA now uses the same configured count of closed bars in live and replay (previously live included a forming bar in its count while replay used an arbitrary 120-bar minimum). Both models are rerun with this alignment.",
        "caveats":["These historical dates were previously examined; this is not untouched future validation.",
                   "Training windows overlap; their sums are not independent observations or portfolio returns.",
                   "SELL rules are unchanged, but realized SELL opportunities can differ when fewer long positions occupy capacity.",
                   "Commission/slippage are unverified assumptions; no swap, latency or full tick reconstruction."],
        "broker_connections":False,"trading_calls":False,
    }
    (output/"plan.json").write_text(json.dumps(plan,indent=2,allow_nan=False),encoding="utf-8")
    records, tasks_by_key = {}, {}
    def task(cfg,start,end,scenario):
        payload=[asdict(cfg),plan["risk_runtime"],start.isoformat(),end.isoformat(),asdict(scenario),history_hash,code_hash]
        key=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        item=(key,source.config,cfg,start,end,scenario,str(cache))
        tasks_by_key[key]=item
        return item
    def batch(items,pool,label):
        unique={item[0]:item for item in items if item[0] not in records}
        futures=[pool.submit(_replay,item) for item in unique.values()]
        for index,future in enumerate(as_completed(futures),1):
            key,record=future.result();records[key]=record
            print(f"{label}: {index}/{len(futures)}",flush=True)
    def record(item):
        raw=records[item[0]]
        trades=[ClosedTrade(**t) for t in raw["trades"]]
        return {"metrics":raw["metrics"],"buy_metrics":trade_metrics([t for t in trades if t.side=="BUY"],10000)}
    cfgs, fits = {}, {}
    print("Registered BUY-only filter study; baseline training first",flush=True)
    with ProcessPoolExecutor(max_workers=workers,initializer=_initialize_worker,initargs=(str(history_path),)) as pool:
        batch([task(base,f.train_start,f.train_end,costs) for f in folds],pool,"baseline training")
        training, selections = {}, {}
        for f in folds:
            item=task(base,f.train_start,f.train_end,costs)
            trades=[ClosedTrade(**t) for t in records[item[0]]["trades"]]
            fit=fit_thresholds(history,base,trades,f.train_start,f.train_end)
            fits[f.index]=fit;cfgs[f.index]={"off":base}
            for name,threshold in fit["thresholds"].items():
                cfgs[f.index][name]=replace(base,long_entry_filter_mode="ema_slope_atr",long_entry_min_slope_atr=threshold)
        batch([task(cfg,f.train_start,f.train_end,costs) for f in folds
               for name,cfg in cfgs[f.index].items() if name!="off"],pool,"filtered training")
        for f in folds:
            training[f.index]={name:record(task(cfg,f.train_start,f.train_end,costs)) for name,cfg in cfgs[f.index].items()}
            selected,reasons=select_profit(training[f.index])
            selections[f.index]={"selected":selected,"threshold":cfgs[f.index][selected].long_entry_min_slope_atr,
                                  "rejections":reasons,"training":training[f.index],"fit":fits[f.index]}
        (output/"locked_selections.json").write_text(json.dumps(selections,indent=2,allow_nan=False),encoding="utf-8")
        print("Selections locked before test replay:",{i:s["selected"] for i,s in selections.items()},flush=True)
        batch([task(cfgs[f.index][name],f.test_start,f.test_end,costs) for f in folds
               for name in {"off",selections[f.index]["selected"]}],pool,"test")
        batch([task(cfgs[f.index][name],f.test_start,f.test_end,stress) for f in folds[6:]
               for name in {"off",selections[f.index]["selected"]}],pool,"stress confirmation")
    def collect(windows,selected,scenario):
        return [ClosedTrade(**trade) for f in windows
                for trade in records[task(cfgs[f.index][selections[f.index]["selected"] if selected else "off"],
                    f.test_start,f.test_end,scenario)[0]]["trades"]]
    def totals(windows,scenario):
        return {label:{"metrics":trade_metrics(collect(windows,selected,scenario),10000),
                       "sides":side_metrics(collect(windows,selected,scenario))}
                for label,selected in [("baseline",False),("filtered_policy",True)]}
    aggregate,confirm,stressed=totals(folds,costs),totals(folds[6:],costs),totals(folds[6:],stress)
    b,c=aggregate["baseline"]["metrics"],aggregate["filtered_policy"]["metrics"]
    bh,ch=confirm["baseline"]["metrics"],confirm["filtered_policy"]["metrics"]
    bs,cs=stressed["baseline"]["metrics"],stressed["filtered_policy"]["metrics"]
    gates={"filter_selected":any(s["selected"]!="off" for s in selections.values()),
           "aggregate_net_improved":c["net_pnl"]>b["net_pnl"],
           "aggregate_drawdown_controlled":c["max_realized_drawdown"]<=1.25*b["max_realized_drawdown"],
           "confirmation_positive_and_improved":ch["net_pnl"]>max(0,bh["net_pnl"]),
           "confirmation_sample_20":ch["trades"]>=20,
           "confirmation_drawdown_controlled":ch["max_realized_drawdown"]<=1.25*bh["max_realized_drawdown"],
           "stress_positive_and_not_worse":cs["net_pnl"]>0 and cs["net_pnl"]>=bs["net_pnl"]}
    per_fold=[{"fold":f.index,"test_start":f.test_start.isoformat(),"selected":selections[f.index]["selected"],
               "threshold":selections[f.index]["threshold"],
               **{label:record(task(cfgs[f.index][name],f.test_start,f.test_end,costs))
                  for label,name in [("baseline","off"),("filtered_policy",selections[f.index]["selected"])]}}
              for f in folds]
    report={"plan":plan,"selections":selections,"aggregate":aggregate,"confirmation":confirm,
            "stress_confirmation":stressed,"promotion_gates":gates,"promotion_passed":all(gates.values()),
            "per_fold":per_fold,"unique_replays":len(records)}
    (output/"report.json").write_text(json.dumps(report,indent=2,allow_nan=False),encoding="utf-8")
    print("FINISHED",json.dumps({"aggregate":aggregate,"confirmation":confirm,"stress":stressed,"gates":gates}),flush=True)
    return report


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history",type=Path,required=True)
    parser.add_argument("--output",type=Path,default=Path("reports/usdchf_long_filter"))
    parser.add_argument("--workers",type=int,default=6)
    args=parser.parse_args()
    if args.workers<1:parser.error("Workers must be positive")
    run(args.history,args.output,args.workers)


if __name__=="__main__":main()
