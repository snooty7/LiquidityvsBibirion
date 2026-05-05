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


class FakeMT5CloseFallback(FakeMT5):
    DEAL_ENTRY_OUT = 1

    def history_deals_get(self, date_from, date_to):
        return [
            SimpleNamespace(
                position_id=0,
                entry=self.DEAL_ENTRY_OUT,
                symbol="EURUSD",
                magic=92001,
                time=200,
                time_msc=200000,
                volume=0.25,
                price=1.1550,
                profit=12.5,
                commission=0.0,
                swap=0.0,
                fee=0.0,
            )
        ]


class FakeMT5CloseByPosition(FakeMT5):
    DEAL_ENTRY_OUT = 1

    def __init__(self) -> None:
        super().__init__()
        self.range_calls = 0

    def history_deals_get(self, *args, **kwargs):
        if "position" in kwargs:
            return [
                SimpleNamespace(
                    position_id=123456,
                    entry=self.DEAL_ENTRY_OUT,
                    symbol="EURUSD",
                    magic=92001,
                    time=200,
                    time_msc=200000,
                    volume=0.25,
                    price=1.1560,
                    profit=10.0,
                    commission=0.0,
                    swap=0.0,
                    fee=0.0,
                )
            ]
        self.range_calls += 1
        return []


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


def test_latest_close_deal_for_position_falls_back_to_symbol_magic_volume_match(monkeypatch) -> None:
    fake = FakeMT5CloseFallback()
    monkeypatch.setattr(mt5_adapter, "mt5", fake)

    adapter = mt5_adapter.MT5Adapter()
    from datetime import datetime, timezone

    deal = adapter.latest_close_deal_for_position(
        123456,
        datetime.fromtimestamp(200000, tz=timezone.utc),
        symbol="EURUSD",
        magic=92001,
        opened_at=100,
        volume=0.25,
    )
    assert deal is not None
    assert deal.price == 1.1550


def test_latest_close_deal_for_position_prefers_direct_position_lookup(monkeypatch) -> None:
    fake = FakeMT5CloseByPosition()
    monkeypatch.setattr(mt5_adapter, "mt5", fake)

    adapter = mt5_adapter.MT5Adapter()
    from datetime import datetime, timezone

    deal = adapter.latest_close_deal_for_position(
        123456,
        datetime.fromtimestamp(200000, tz=timezone.utc),
        symbol="EURUSD",
        magic=92001,
        opened_at=100,
        volume=0.25,
    )
    assert deal is not None
    assert deal.price == 1.1560
    assert fake.range_calls == 0


class FakeMT5CloseOrderSend(FakeMT5):
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1
    TRADE_ACTION_DEAL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_DONE_PARTIAL = 10010
    TRADE_RETCODE_INVALID_FILL = 10030
    TRADE_RETCODE_PRICE_CHANGED = 10020

    def __init__(self, results) -> None:
        super().__init__()
        self.results = list(results)
        self.requests = []

    def symbol_info(self, symbol):
        return SimpleNamespace(name=symbol, visible=True, select=True, digits=5, point=0.00001)

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(
            bid=1.10001 + len(self.requests) * 0.00001,
            ask=1.10003 + len(self.requests) * 0.00001,
        )

    def order_send(self, request):
        self.requests.append(dict(request))
        if self.results:
            return self.results.pop(0)
        return None

    def last_error(self):
        return (-1, "Terminal: Call failed")


def test_close_position_retries_after_none_result(monkeypatch) -> None:
    fake = FakeMT5CloseOrderSend([
        None,
        SimpleNamespace(retcode=FakeMT5CloseOrderSend.TRADE_RETCODE_DONE, order=123, deal=456),
    ])
    monkeypatch.setattr(mt5_adapter, "mt5", fake)

    result = mt5_adapter.MT5Adapter(default_deviation=20).close_position_market_with_fallback(
        symbol="EURUSD",
        position=SimpleNamespace(type=FakeMT5CloseOrderSend.POSITION_TYPE_BUY, ticket=10, volume=0.1),
        magic=92014,
        reason="adverse_close_exit 1bars",
    )

    assert result.ok is True
    assert result.retcode == FakeMT5CloseOrderSend.TRADE_RETCODE_DONE
    assert len(fake.requests) == 2
    assert fake.shutdown_calls == 1
    assert fake.initialize_calls == 1


def test_close_position_returns_last_error_payload_when_mt5_returns_none(monkeypatch) -> None:
    fake = FakeMT5CloseOrderSend([None, None, None, None, None, None, None, None, None])
    monkeypatch.setattr(mt5_adapter, "mt5", fake)

    result = mt5_adapter.MT5Adapter(default_deviation=20).close_position_market_with_fallback(
        symbol="EURUSD",
        position=SimpleNamespace(type=FakeMT5CloseOrderSend.POSITION_TYPE_SELL, ticket=11, volume=0.1),
        magic=92014,
        reason="adverse_close_exit 1bars",
    )

    assert result.ok is False
    assert result.raw["last_error"] == (-1, "Terminal: Call failed")
    assert result.raw["request"]["position"] == 11
    assert result.raw["request"]["volume"] == 0.1
