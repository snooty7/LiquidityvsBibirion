"""Presentation adapter for optional adaptive observations; never executes trades."""
from dataclasses import asdict

from src.risk.sizing import RiskSizingError, calc_lot_by_risk, calc_position_risk_money, pip_size
from src.strategy.adaptive.context import snapshot
from src.strategy.adaptive.engine import evaluate
from src.strategy.adaptive.ml_shadow import observe
from src.strategy.adaptive.models import VERSION


def build_observation(*, symbol, decision_time, rates, config, info, equity, risk_pct,
                      max_lot, min_lot, comparison=()):
    """Build an indicative close-price proposal, clearly separate from executable quotes."""
    context = snapshot(symbol, decision_time, rates, config)
    bars = context.bars(config.entry_timeframe)
    price = bars[-1].close if bars else 1.0
    result = evaluate(context, config, pip=pip_size(info.digits, info.point),
                      tick_size=info.trade_tick_size, entry_price=price)
    risk = None
    if result.proposal:
        proposal = result.proposal
        try:
            volume = calc_lot_by_risk(equity, abs(price-proposal.sl)/pip_size(info.digits, info.point),
                                      risk_pct, info, max_lot, min_lot)
            risk = dict(volume=volume, risk_money=calc_position_risk_money(price, proposal.sl, volume, info),
                        risk_pct=risk_pct, status="indicative_not_preflight_approved")
        except RiskSizingError as exc:
            risk = dict(status="sizing_rejected", reason=str(exc))
    return dict(status="observation_only_no_live_route", decision_time=decision_time,
                price_basis="last_completed_entry_close_not_executable_quote", version=VERSION,
                evaluation=asdict(result), proposed_risk=risk,
                shadow=asdict(observe(tuple(item.value or 0 for item in result.score.observations))) if config.ml_shadow else None,
                comparison=list(comparison), config_digest=config.digest(), source_digest=context.source_digest)
