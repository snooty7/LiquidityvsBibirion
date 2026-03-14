from src.strategy.filters import (
    evaluate_bias,
    find_local_order_block,
    order_block_distance_pips,
)


def test_evaluate_bias_buy_context() -> None:
    rates = []
    base = 1.1000
    for idx in range(40):
        rates.append({"close": base + idx * 0.0005})

    info = evaluate_bias(rates, ema_period=20)

    assert info["ok_buy"] is True
    assert info["ok_sell"] is False


def test_find_local_order_block_buy_side() -> None:
    rates = [
        {"time": 1, "open": 1.1000, "high": 1.1010, "low": 1.0990, "close": 1.1008},
        {"time": 2, "open": 1.1000, "high": 1.1005, "low": 1.0985, "close": 1.0990},
        {"time": 3, "open": 1.0992, "high": 1.1020, "low": 1.0990, "close": 1.1015},
        {"time": 4, "open": 1.1014, "high": 1.1025, "low": 1.1010, "close": 1.1020},
    ]

    ob = find_local_order_block(
        rates=rates,
        signal_index=3,
        side="BUY",
        pip=0.0001,
        lookback_bars=20,
        max_age_bars=15,
        zone_mode="body",
        min_impulse_pips=3.0,
    )

    assert ob is not None
    assert ob["kind"] == "BULLISH_OB"

    dist = order_block_distance_pips(entry_price=1.1002, ob_low=ob["low"], ob_high=ob["high"], pip=0.0001)
    assert dist >= 0.0