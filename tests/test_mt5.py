from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from forexbot.mt5 import MT5MarketData


def test_fetch_candles_converts_mt5_rates() -> None:
    client = SimpleNamespace(
        TIMEFRAME_M15=15,
        symbol_select=lambda symbol, visible: True,
        copy_rates_from_pos=lambda symbol, timeframe, start, count: [
            {"time": 1_700_000_000, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15},
            {"time": 1_700_000_900, "open": 1.15, "high": 1.25, "low": 1.1, "close": 1.2},
        ],
    )
    candles = MT5MarketData(client=client).fetch_candles("EURUSD", "M15", 2)

    assert len(candles) == 2
    assert candles[0].close == 1.15


def test_fetch_quote_reports_current_bid_ask_and_spread() -> None:
    client = SimpleNamespace(
        symbol_select=lambda symbol, visible: True,
        symbol_info=lambda symbol: SimpleNamespace(point=0.00001),
        symbol_info_tick=lambda symbol: SimpleNamespace(
            bid=1.1,
            ask=1.1002,
            time=int(datetime.now(UTC).timestamp()),
        ),
    )

    quote = MT5MarketData(client=client, server_utc_offset_hours=0).fetch_quote("EURUSD")

    assert quote["bid"] == 1.1
    assert quote["ask"] == 1.1002
    assert quote["spread_points"] == pytest.approx(20)
