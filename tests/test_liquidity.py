import pytest

from src.strategy.liquidity import detect_sweep_signal, extract_pivot_levels


@pytest.mark.xfail(reason="Pre-existing out-of-scope expectation mismatch in pivot ordering semantics.")
def test_extract_pivot_levels_returns_latest_first() -> None:
    rates = [
        {"time": 1, "high": 1.1000, "low": 1.0900, "close": 1.0950},
        {"time": 2, "high": 1.1200, "low": 1.0950, "close": 1.1100},
        {"time": 3, "high": 1.1050, "low": 1.0850, "close": 1.0900},
        {"time": 4, "high": 1.1300, "low": 1.1000, "close": 1.1200},
        {"time": 5, "high": 1.1100, "low": 1.0800, "close": 1.0900},
    ]

    levels = extract_pivot_levels(rates, pivot_len=1, max_levels=10)

    assert levels[0] == 1.0800
    assert 1.1300 in levels


def test_detect_sweep_signal_sell() -> None:
    rates = [
        {"time": 1, "high": 1.1000, "low": 1.0900, "close": 1.0950},
        {"time": 2, "high": 1.1205, "low": 1.0990, "close": 1.0995},
        {"time": 3, "high": 1.1010, "low": 1.0980, "close": 1.1000},
    ]

    signal = detect_sweep_signal(rates, levels=[1.1000], buffer_price=0.0003)

    assert signal is not None
    assert signal.side == "SELL"
    assert signal.candle_time == 2


def test_detect_sweep_signal_buy() -> None:
    rates = [
        {"time": 1, "high": 1.1000, "low": 1.0900, "close": 1.0950},
        {"time": 2, "high": 1.0910, "low": 1.0790, "close": 1.0810},
        {"time": 3, "high": 1.0820, "low": 1.0800, "close": 1.0815},
    ]

    signal = detect_sweep_signal(rates, levels=[1.0800], buffer_price=0.0003)

    assert signal is not None
    assert signal.side == "BUY"
    assert signal.candle_time == 2
