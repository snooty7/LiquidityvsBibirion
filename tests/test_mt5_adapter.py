from types import SimpleNamespace

from src.execution import mt5_adapter


class FakeMT5:
    def __init__(self) -> None:
        self.initialized = True
        self.symbol_info_calls = 0
        self.select_calls = 0
        self.shutdown_calls = 0
        self.initialize_calls = 0

    def initialize(self):
        self.initialize_calls += 1
        self.initialized = True
        return True

    def shutdown(self):
        self.shutdown_calls += 1
        self.initialized = False

    def last_error(self):
        return (1, "Success")

    def symbol_info(self, symbol):
        self.symbol_info_calls += 1
        if self.symbol_info_calls < 3:
            return None
        return SimpleNamespace(name=symbol, visible=True, select=True)

    def symbol_select(self, symbol, selected):
        self.select_calls += 1
        return True

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, bars):
        return [1, 2, 3]

    def copy_rates_range(self, symbol, timeframe, date_from, date_to):
        return [4, 5, 6]

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(bid=1.1000, ask=1.1002)

    def positions_get(self, symbol=None):
        return []

    TIMEFRAME_M5 = 5


class FakeMT5Missing(FakeMT5):
    def symbol_info(self, symbol):
        self.symbol_info_calls += 1
        return None


class FakeMT5PositionsRetry(FakeMT5):
    def __init__(self) -> None:
        super().__init__()
        self.positions_calls = 0

    def positions_get(self, symbol=None):
        self.positions_calls += 1
        if self.positions_calls == 1:
            return None
        return [SimpleNamespace(ticket=1, magic=92001)]


def test_symbol_info_recovers_after_reinitialize(monkeypatch) -> None:
    fake = FakeMT5()
    monkeypatch.setattr(mt5_adapter, "mt5", fake)

    adapter = mt5_adapter.MT5Adapter()
    info = adapter.symbol_info("EURUSD")

    assert info is not None
    assert info.name == "EURUSD"
    assert fake.select_calls >= 1
    assert fake.shutdown_calls == 1
    assert fake.initialize_calls == 1


def test_symbol_info_raises_if_symbol_still_missing(monkeypatch) -> None:
    fake = FakeMT5Missing()
    monkeypatch.setattr(mt5_adapter, "mt5", fake)

    adapter = mt5_adapter.MT5Adapter()

    try:
        adapter.symbol_info("EURUSD")
        raise AssertionError("Expected RuntimeError for missing symbol")
    except RuntimeError as exc:
        assert "Unknown symbol: EURUSD" in str(exc)


def test_positions_get_retries_after_none(monkeypatch) -> None:
    fake = FakeMT5PositionsRetry()
    monkeypatch.setattr(mt5_adapter, "mt5", fake)

    adapter = mt5_adapter.MT5Adapter()
    positions = adapter.positions_get("EURUSD", magic=92001)

    assert len(positions) == 1
    assert fake.positions_calls == 2
    assert fake.select_calls >= 1


def test_copy_rates_range_returns_data(monkeypatch) -> None:
    fake = FakeMT5()
    monkeypatch.setattr(mt5_adapter, "mt5", fake)

    adapter = mt5_adapter.MT5Adapter()
    rates = adapter.copy_rates_range("EURUSD", "M5", None, None)

    assert rates == [4, 5, 6]
