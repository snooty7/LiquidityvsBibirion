"""Offline adapters joining the adaptive evaluator to the unchanged baseline replay."""
from bisect import bisect_right
from dataclasses import asdict, replace
from types import SimpleNamespace

from src.backtesting.history import HistoricalData, TIMEFRAMES
from src.risk.preflight import BrokerLimits, check_entry
from src.risk.sizing import pip_size
from src.strategy.adaptive.config import AdaptiveConfig
from src.strategy.adaptive.context import snapshot
from src.strategy.adaptive.engine import evaluate
from src.strategy.adaptive.exits import decide_exit
from src.strategy.adaptive.ml_shadow import observe
from src.strategy.adaptive.models import Regime

ARMS = ("baseline", "regime", "scoring", "adaptive", "adaptive_shadow")


class AdaptiveReplayPolicy:
    """One isolated branch/fold policy; no broker imports or execution calls.

    The full arm adapts qualified baseline candidates, rather than inventing a
    second candidate stream. Legacy final filters and risk checks still run.
    """

    def __init__(self, history: HistoricalData, config: AdaptiveConfig, arm: str):
        if arm not in ARMS or not config.enabled:
            raise ValueError("Choose an enabled experimental configuration and known arm")
        self.history, self.config, self.arm = history, config, arm
        self.observations = []
        self.seen = set()
        self.exit_observations = []
        self.milestones = {}

    def entry(self, *, cfg, runtime, info, equity, side, timestamp, price,
              quoted_price, pending, costs, spread_pips):
        """Filter a legacy candidate or supply adaptive protection before sizing."""
        config = self.config
        required = (config.entry_timeframe, *config.context_timeframes)
        rates = {}
        for tf in required:
            end = bisect_right(self.history.timestamps(tf), timestamp-TIMEFRAMES[tf])
            rates[tf] = self.history.bars(tf)[max(0, end-config.lookback):end]
        context = snapshot(cfg.symbol, timestamp, rates, config)
        pip = pip_size(info.digits, info.point)
        result = evaluate(context, config, pip=pip, tick_size=info.trade_tick_size,
                          entry_price=price, candidate_side=side, seen_keys=frozenset(self.seen))
        reasons = [] if self.arm == "baseline" else list(context.reasons)
        if self.arm == "regime":
            if result.regime.regime in {Regime.UNCERTAIN, Regime.HIGH_VOLATILITY}:
                reasons.append("regime_block")
            if result.regime.regime == Regime.TRENDING_BULLISH and side != "BUY" or result.regime.regime == Regime.TRENDING_BEARISH and side != "SELL":
                reasons.append("regime_direction_conflict")
        elif self.arm == "scoring":
            reasons.extend(result.score.reasons)
        elif self.arm != "baseline":
            reasons.extend(result.reasons)
        event = dict(timestamp=timestamp, side=side, regime=result.regime.regime.value,
                     evaluation=asdict(result), reasons=reasons, shadow=None,
                     signal_key=pending.signal_key if pending else None)
        if self.arm == "adaptive_shadow":
            event["shadow"] = asdict(observe(tuple(item.value or 0 for item in result.score.observations)))
        self.observations.append(event)
        if reasons:
            return None
        if self.arm in {"baseline", "regime", "scoring"}:
            return {}
        proposal = result.proposal
        if proposal is None:
            return None
        # This replay holds one position at a time. Portfolio simulation is a
        # separate concern, never fake other positions as known/zero in live use.
        preflight = check_entry(
            side=side, symbol=cfg.symbol, price=price, sl=proposal.sl, tp=proposal.tp,
            equity=equity, risk_pct=cfg.risk_pct, authorized_risk_pct=cfg.risk_pct,
            info=info, limits=BrokerLimits(0, 0, info.trade_tick_size), max_lot=cfg.max_lot,
            min_lot=cfg.min_lot, spread_pips=spread_pips, max_spread_pips=cfg.max_spread_pips,
            quote_time=timestamp, decision_time=timestamp, max_quote_age=1,
            realized_today=0, daily_limit=runtime.daily_loss_limit_usd, positions=(),
            portfolio_cap_pct=runtime.max_total_open_risk_pct, max_positions=runtime.max_open_positions_total,
            currency_cap_pct=config.currency_cap_pct, correlation_cap_pct=config.correlation_cap_pct,
            correlations={}, min_rr=config.min_rr,
            round_trip_cost_price=(2*costs.slippage_pips + 2*costs.commission_per_lot /
                                   (info.trade_tick_value*pip/info.trade_tick_size))*pip if costs else 0,
            research=True)
        event["preflight"] = asdict(preflight)
        if not preflight.allowed:
            event["reasons"].extend(preflight.reasons)
            return None
        self.seen.add(proposal.key)
        return {"sl_price": proposal.sl, "tp_price": proposal.tp, "risk_pct_override": cfg.risk_pct}

    def exit(self, trade, bar, info):
        """Tighten at a completed M1 close; existing loss/exit guards take priority."""
        if self.arm not in {"adaptive", "adaptive_shadow"}:
            return []
        spread = trade.costs.spread(bar, info) if trade.costs else 0
        price = bar["close"] + (spread*pip_size(info.digits, info.point) if trade.side == "SELL" else 0)
        key = (trade.entry_time, trade.signal_key)
        completed = frozenset(self.milestones.get(key, set()))
        decision = decide_exit(side=trade.side, entry=trade.entry_price, initial_stop=trade.initial_sl,
                               current_stop=trade.sl, exit_price=price, volume=trade.volume,
                               info=info, config=self.config, completed=completed)
        if decision.stop is not None:
            trade.sl = decision.stop
            self.exit_observations.append(dict(available_at=bar["time"]+60, decision=asdict(decision)))
        if decision.close_volume:
            from src.tools.backtest_mt5 import _close_trade

            fraction = decision.close_volume/trade.volume
            fields = ("risk_money", "entry_commission_money", "exit_commission_money",
                      "entry_spread_cost_money", "entry_slippage_cost_money")
            allocation = {name: getattr(trade, name)*fraction for name in fields}
            partial = replace(trade, volume=decision.close_volume, **allocation)
            closed = _close_trade(SimpleNamespace(symbol=self.history.symbol), partial, bar["time"]+60, price, "adaptive_partial", info,
                                  spread_pips=spread)
            trade.volume -= decision.close_volume
            for name, amount in allocation.items():
                setattr(trade, name, getattr(trade, name)-amount)
            self.milestones.setdefault(key, set()).add(decision.milestone)
            self.exit_observations.append(dict(available_at=bar["time"]+60, decision=asdict(decision)))
            return [closed]
        return []
