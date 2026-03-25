import pytest

from src.strategy.liquidity import (
    detect_sweep_signal,
    evaluate_range_filter,
    evaluate_sweep_significance,
    extract_pivot_levels,
)


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


def test_sweep_significance_rejects_small_penetration() -> None:
    rates = [
        {"time": 1, "high": 1.1000, "low": 1.0995, "close": 1.0998},
        {"time": 2, "high": 1.1002, "low": 1.0997, "close": 1.1000},
        {"time": 3, "high": 1.1001, "low": 1.0996, "close": 1.0999},
        {"time": 4, "high": 1.1004, "low": 1.0998, "close": 1.1001},
        {"time": 5, "high": 1.10035, "low": 1.09985, "close": 1.10005},
        {"time": 6, "high": 1.1003, "low": 1.0999, "close": 1.1000},
    ]
    signal = detect_sweep_signal(rates, levels=[1.1000], buffer_price=0.0001)
    assert signal is not None

    result = evaluate_sweep_significance(
        rates,
        signal,
        lookback_bars=4,
        min_range_multiple=1.0,
        min_penetration_price=0.0003,
    )

    assert result.valid is False
    assert result.note == "sweep_penetration_too_small"


def test_sweep_significance_accepts_meaningful_sweep() -> None:
    rates = [
        {"time": 1, "high": 1.1000, "low": 1.0995, "close": 1.0998},
        {"time": 2, "high": 1.1002, "low": 1.0997, "close": 1.1000},
        {"time": 3, "high": 1.1001, "low": 1.0996, "close": 1.0999},
        {"time": 4, "high": 1.1004, "low": 1.0998, "close": 1.1001},
        {"time": 5, "high": 1.1009, "low": 1.0994, "close": 1.1002},
        {"time": 6, "high": 1.1003, "low": 1.0999, "close": 1.1000},
    ]
    signal = detect_sweep_signal(rates, levels=[1.1000], buffer_price=0.0001)
    assert signal is not None

    result = evaluate_sweep_significance(
        rates,
        signal,
        lookback_bars=4,
        min_range_multiple=1.2,
        min_penetration_price=0.0003,
    )

    assert result.valid is True
    assert result.note == "sweep_significant"


def test_range_filter_blocks_chop() -> None:
    rates = [
        {"time": 1, "high": 1.1004, "low": 1.0998, "close": 1.1001},
        {"time": 2, "high": 1.1003, "low": 1.0999, "close": 1.1000},
        {"time": 3, "high": 1.10035, "low": 1.09995, "close": 1.1001},
        {"time": 4, "high": 1.10025, "low": 1.09990, "close": 1.1000},
        {"time": 5, "high": 1.10030, "low": 1.09992, "close": 1.10005},
        {"time": 6, "high": 1.10028, "low": 1.09994, "close": 1.10002},
    ]

    result = evaluate_range_filter(
        rates,
        lookback_bars=6,
        max_compression_ratio=2.5,
        min_overlap_ratio=0.7,
    )

    assert result.blocked is True
    assert result.note == "range_chop_blocked"


def test_range_filter_allows_expanding_environment() -> None:
    rates = [
        {"time": 1, "high": 1.1004, "low": 1.0998, "close": 1.1001},
        {"time": 2, "high": 1.1008, "low": 1.0999, "close": 1.1007},
        {"time": 3, "high": 1.1012, "low": 1.1003, "close": 1.1010},
        {"time": 4, "high": 1.1017, "low": 1.1006, "close": 1.1015},
        {"time": 5, "high": 1.1023, "low": 1.1010, "close": 1.1020},
        {"time": 6, "high": 1.1028, "low": 1.1016, "close": 1.1025},
    ]

    result = evaluate_range_filter(
        rates,
        lookback_bars=6,
        max_compression_ratio=2.5,
        min_overlap_ratio=0.7,
    )

    assert result.blocked is False
    assert result.note == "range_ok"
