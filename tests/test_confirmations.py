from src.strategy.confirmations import (
    evaluate_c3_c4_confirmation,
    evaluate_cisd_confirmation,
)


def test_c3_confirmation_success() -> None:
    rates = [
        {"time": 1, "open": 1.0990, "high": 1.1012, "low": 1.0988, "close": 1.1008},
        {"time": 2, "open": 1.1005, "high": 1.1018, "low": 1.1002, "close": 1.1016},
        {"time": 3, "open": 1.1015, "high": 1.1020, "low": 1.1010, "close": 1.1018},
    ]

    result = evaluate_c3_c4_confirmation(rates, side="BUY", sweep_candle_time=1, mode="c3")

    assert result.confirmed is True
    assert result.pending is False


def test_c4_confirmation_waiting() -> None:
    rates = [
        {"time": 1, "open": 1.0990, "high": 1.1012, "low": 1.0988, "close": 1.1008},
        {"time": 2, "open": 1.1005, "high": 1.1018, "low": 1.1002, "close": 1.1016},
        {"time": 3, "open": 1.1015, "high": 1.1020, "low": 1.1010, "close": 1.1018},
    ]

    result = evaluate_c3_c4_confirmation(rates, side="BUY", sweep_candle_time=1, mode="c4")

    assert result.confirmed is False
    assert result.pending is True


def test_cisd_confirmation_buy() -> None:
    rates = [
        {"time": 1, "open": 1.1000, "high": 1.1005, "low": 1.0995, "close": 1.1002},
        {"time": 2, "open": 1.1002, "high": 1.1008, "low": 1.0998, "close": 1.1006},
        {"time": 3, "open": 1.1006, "high": 1.1011, "low": 1.1000, "close": 1.1009},
        {"time": 4, "open": 1.1009, "high": 1.1016, "low": 1.1003, "close": 1.1015},
        {"time": 5, "open": 1.1015, "high": 1.1022, "low": 1.1008, "close": 1.1020},
        {"time": 6, "open": 1.1020, "high": 1.1025, "low": 1.1010, "close": 1.1022},
    ]

    result = evaluate_cisd_confirmation(rates, side="BUY", since_ts=1, structure_bars=4)

    assert result.confirmed is True
    assert result.pending is False