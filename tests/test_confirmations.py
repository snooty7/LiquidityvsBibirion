from src.strategy.confirmations import (
    evaluate_c3_c4_confirmation,
    evaluate_cisd_confirmation,
    evaluate_sweep_displacement_mss_confirmation,
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


def test_sweep_displacement_mss_confirmation_buy_success() -> None:
    rates = [
        {"time": 1, "open": 1.1000, "high": 1.1004, "low": 1.0997, "close": 1.1001},
        {"time": 2, "open": 1.1001, "high": 1.1003, "low": 1.0998, "close": 1.1000},
        {"time": 3, "open": 1.1000, "high": 1.1002, "low": 1.0997, "close": 1.0999},
        {"time": 4, "open": 1.0999, "high": 1.1012, "low": 1.0998, "close": 1.1011},
        {"time": 5, "open": 1.1010, "high": 1.1015, "low": 1.1007, "close": 1.1014},
        {"time": 6, "open": 1.1014, "high": 1.1016, "low": 1.1010, "close": 1.1013},
    ]

    result = evaluate_sweep_displacement_mss_confirmation(
        rates,
        side="BUY",
        since_ts=1,
        structure_bars=3,
        displacement_range_multiple=1.1,
    )

    assert result.confirmed is True
    assert result.pending is False
    assert result.note == "sdmss_buy_confirmed"


def test_sweep_displacement_mss_confirmation_buy_confirms_without_extra_follow_through() -> None:
    rates = [
        {"time": 1, "open": 1.1000, "high": 1.1004, "low": 1.0997, "close": 1.1001},
        {"time": 2, "open": 1.1001, "high": 1.1003, "low": 1.0998, "close": 1.1000},
        {"time": 3, "open": 1.1000, "high": 1.1002, "low": 1.0997, "close": 1.0999},
        {"time": 4, "open": 1.0999, "high": 1.1012, "low": 1.0998, "close": 1.1011},
        {"time": 5, "open": 1.1010, "high": 1.1011, "low": 1.1007, "close": 1.1009},
        {"time": 6, "open": 1.1009, "high": 1.1010, "low": 1.1006, "close": 1.1008},
    ]

    result = evaluate_sweep_displacement_mss_confirmation(
        rates,
        side="BUY",
        since_ts=1,
        structure_bars=3,
        displacement_range_multiple=1.1,
    )

    assert result.confirmed is True
    assert result.pending is False
    assert result.note == "sdmss_buy_confirmed"


def test_sweep_displacement_mss_confirmation_stays_pending_without_displacement() -> None:
    rates = [
        {"time": 1, "open": 1.1000, "high": 1.1004, "low": 1.0997, "close": 1.1001},
        {"time": 2, "open": 1.1001, "high": 1.1003, "low": 1.0998, "close": 1.1000},
        {"time": 3, "open": 1.1000, "high": 1.1002, "low": 1.0997, "close": 1.0999},
        {"time": 4, "open": 1.0999, "high": 1.1005, "low": 1.0998, "close": 1.1002},
        {"time": 5, "open": 1.1002, "high": 1.1006, "low": 1.0999, "close": 1.1003},
        {"time": 6, "open": 1.1003, "high": 1.1007, "low": 1.1000, "close": 1.1004},
    ]

    result = evaluate_sweep_displacement_mss_confirmation(
        rates,
        side="BUY",
        since_ts=1,
        structure_bars=3,
        displacement_range_multiple=1.1,
    )

    assert result.confirmed is False
    assert result.pending is True
    assert result.note == "sdmss_wait_displacement"


def test_sweep_displacement_mss_confirmation_waits_for_bos_after_impulse() -> None:
    rates = [
        {"time": 1, "open": 1.1000, "high": 1.1004, "low": 1.0997, "close": 1.1001},
        {"time": 2, "open": 1.1001, "high": 1.1006, "low": 1.0998, "close": 1.1000},
        {"time": 3, "open": 1.1000, "high": 1.1005, "low": 1.0997, "close": 1.0999},
        {"time": 4, "open": 1.0998, "high": 1.10065, "low": 1.09975, "close": 1.10035},
        {"time": 5, "open": 1.1004, "high": 1.1005, "low": 1.1000, "close": 1.1003},
        {"time": 6, "open": 1.1003, "high": 1.1004, "low": 1.1000, "close": 1.1002},
    ]

    result = evaluate_sweep_displacement_mss_confirmation(
        rates,
        side="BUY",
        since_ts=1,
        structure_bars=3,
        displacement_range_multiple=1.1,
    )

    assert result.confirmed is False
    assert result.pending is True
    assert result.note == "sdmss_wait_bos"


def test_sweep_displacement_mss_confirmation_sell_success() -> None:
    rates = [
        {"time": 1, "open": 1.2000, "high": 1.2003, "low": 1.1998, "close": 1.2001},
        {"time": 2, "open": 1.2001, "high": 1.2004, "low": 1.1999, "close": 1.2002},
        {"time": 3, "open": 1.2002, "high": 1.2005, "low": 1.2000, "close": 1.2001},
        {"time": 4, "open": 1.2001, "high": 1.2002, "low": 1.1988, "close": 1.1989},
        {"time": 5, "open": 1.1989, "high": 1.1990, "low": 1.1984, "close": 1.1985},
        {"time": 6, "open": 1.1985, "high": 1.1987, "low": 1.1982, "close": 1.1986},
    ]

    result = evaluate_sweep_displacement_mss_confirmation(rates, side="SELL", since_ts=1, structure_bars=3)

    assert result.confirmed is True
    assert result.pending is False
    assert result.note == "sdmss_sell_confirmed"
