from collections.abc import Sequence

from forexbot.domain import Candle, Side, Signal


class MovingAverageCrossover:
    """Example strategy: signals when fast and slow moving averages cross."""

    def __init__(self, fast_period: int = 10, slow_period: int = 30) -> None:
        if fast_period < 1 or fast_period >= slow_period:
            raise ValueError("fast_period must be positive and less than slow_period")
        self.fast_period = fast_period
        self.slow_period = slow_period

    def signal(self, candles: Sequence[Candle]) -> Signal | None:
        if len(candles) < self.slow_period + 1:
            return None
        previous_fast = self._average(candles[-self.fast_period - 1 : -1])
        previous_slow = self._average(candles[-self.slow_period - 1 : -1])
        current_fast = self._average(candles[-self.fast_period :])
        current_slow = self._average(candles[-self.slow_period :])
        price = candles[-1].close
        range_size = max(candles[-1].high - candles[-1].low, price * 0.0001)
        if previous_fast <= previous_slow and current_fast > current_slow:
            return Signal(Side.BUY, price - 2 * range_size, price + 3 * range_size, "MA crossover")
        if previous_fast >= previous_slow and current_fast < current_slow:
            return Signal(Side.SELL, price + 2 * range_size, price - 3 * range_size, "MA crossover")
        return None

    @staticmethod
    def _average(candles: Sequence[Candle]) -> float:
        return sum(candle.close for candle in candles) / len(candles)
