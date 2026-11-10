from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        prices = (self.open, self.high, self.low, self.close)
        if not all(isfinite(price) and price > 0 for price in prices):
            raise ValueError("candle prices must be finite and positive")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("candle high is below another candle price")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("candle low is above another candle price")


@dataclass(frozen=True)
class Signal:
    side: Side
    stop_loss: float
    take_profit: float
    reason: str


@dataclass(frozen=True)
class Trade:
    side: Side
    entry_price: float
    exit_price: float
    units: float
    commission: float = 0.0

    @property
    def profit_loss(self) -> float:
        direction = 1 if self.side is Side.BUY else -1
        return (self.exit_price - self.entry_price) * self.units * direction - self.commission
