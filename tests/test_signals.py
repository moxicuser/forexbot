from datetime import UTC, datetime, timedelta

import pytest

from forexbot.domain import Candle
from forexbot.signals import analyze_market


def _candles(count: int = 60) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Candle(
            start + timedelta(minutes=15 * index),
            1.1 + index * 0.0001,
            1.1002 + index * 0.0001,
            1.0998 + index * 0.0001,
            1.1 + index * 0.0001,
        )
        for index in range(count)
    ]


def test_market_analysis_refuses_stale_quotes() -> None:
    stale_quote = {
        "bid": 1.105,
        "ask": 1.1051,
        "spread_points": 10,
        "timestamp": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
    }

    analysis = analyze_market(_candles(), stale_quote, "EURUSD", "M15")

    assert analysis["signal"] == "WAIT"
    assert "stale" in analysis["reason"]
    assert analysis["execution"] == "read-only analysis; no order placed"


def test_market_analysis_requires_enough_candles() -> None:
    quote = {"bid": 1.1, "ask": 1.1001, "spread_points": 10, "timestamp": datetime.now(UTC).isoformat()}

    with pytest.raises(ValueError, match="51 completed candles"):
        analyze_market(_candles(50), quote, "EURUSD", "M15")


def test_market_analysis_returns_confirmed_buy_setup_with_reference_levels() -> None:
    closes = [1.1]
    for _ in range(45):
        closes.append(closes[-1] + 0.0001)
    for change in [0.0001] * 9 + [-0.0001] * 5:
        closes.append(closes[-1] + change)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles = [
        Candle(
            start + timedelta(minutes=15 * index),
            close,
            close + 0.00005,
            close - 0.00005,
            close,
        )
        for index, close in enumerate(closes)
    ]
    quote = {
        "bid": closes[-1],
        "ask": closes[-1] + 0.0001,
        "spread_points": 10,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    analysis = analyze_market(candles, quote, "EURUSD", "M15")

    assert analysis["signal"] == "BUY SETUP"
    assert analysis["entry_reference"] < analysis["take_profit_reference"]
    assert analysis["stop_loss_reference"] < analysis["entry_reference"]
    assert "20/50-period averages" in analysis["explanation"]
