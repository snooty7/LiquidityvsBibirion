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

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(bid=1.1000, ask=1.1002)

    TIMEFRAME_M5 = 5


class FakeMT5Missing(FakeMT5):
    def symbol_info(self, symbol):
        self.symbol_info_calls += 1
        return None


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
