from datetime import datetime, timedelta

from forexbot.backtest import Backtester
from forexbot.domain import Candle, Side, Signal
from forexbot.risk import RiskLimits, RiskManager


class OneSignalStrategy:
    def signal(self, candles: list[Candle]) -> Signal | None:
        if len(candles) == 2:
            return Signal(Side.BUY, 0.9, 1.2, "test")
        return None


def test_backtester_records_trade_closed_at_take_profit() -> None:
    start = datetime(2026, 1, 1)
    candles = [
        Candle(start, 1, 1, 1, 1),
        Candle(start + timedelta(minutes=1), 1, 1, 1, 1),
        Candle(start + timedelta(minutes=2), 1, 1.3, 0.95, 1.1),
    ]
    result = Backtester(OneSignalStrategy(), RiskManager(RiskLimits()), 10_000).run(candles)

    assert len(result.trades) == 1
    assert result.trades[0].exit_price == 1.2
    assert result.net_profit > 0


def test_backtester_applies_slippage_and_commission() -> None:
    start = datetime(2026, 1, 1)
    candles = [
        Candle(start, 1, 1, 1, 1),
        Candle(start + timedelta(minutes=1), 1, 1, 1, 1),
        Candle(start + timedelta(minutes=2), 1, 1.3, 0.95, 1.1),
    ]
    result = Backtester(
        OneSignalStrategy(),
        RiskManager(RiskLimits()),
        10_000,
        slippage=0.01,
        commission_per_unit=0.001,
    ).run(candles)

    assert result.trades[0].entry_price == 1.01
    assert result.trades[0].exit_price == 1.19
    assert result.trades[0].profit_loss < 180
