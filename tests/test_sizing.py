from src.risk.sizing import SymbolTradeInfo, calc_lot_by_risk, calc_position_risk_money


def test_calc_lot_by_risk_respects_max_and_step() -> None:
    info = SymbolTradeInfo(
        digits=5,
        point=0.00001,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        trade_tick_value=1.0,
        trade_tick_size=0.00001,
    )

    lot = calc_lot_by_risk(
        equity=10000.0,
        sl_pips=10.0,
        risk_pct=1.0,
        symbol_info=info,
        max_lot=0.10,
    )

    assert lot == 0.1


def test_calc_lot_by_risk_handles_broker_fallback() -> None:
    info = SymbolTradeInfo(
        digits=5,
        point=0.00001,
        volume_min=0.01,
        volume_max=1.0,
        volume_step=0.01,
        trade_tick_value=0.0,
        trade_tick_size=0.0,
    )

    lot = calc_lot_by_risk(
        equity=10000.0,
        sl_pips=10.0,
        risk_pct=1.0,
        symbol_info=info,
        max_lot=1.0,
    )

    assert lot >= 0.01


def test_calc_position_risk_money() -> None:
    info = SymbolTradeInfo(
        digits=5,
        point=0.00001,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        trade_tick_value=1.0,
        trade_tick_size=0.00001,
    )

    risk_money = calc_position_risk_money(
        entry_price=1.1000,
        stop_price=1.0990,
        volume=0.10,
        symbol_info=info,
    )

    assert risk_money > 0