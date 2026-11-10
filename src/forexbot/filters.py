"""Market condition filters used before paper entries."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TradingFilters:
    max_spread_points: float | None = 30.0
    start_hour_utc: int = 0
    end_hour_utc: int = 24

    def __post_init__(self) -> None:
        if self.max_spread_points is not None and self.max_spread_points <= 0:
            raise ValueError("max_spread_points must be positive")
        if not 0 <= self.start_hour_utc <= 23:
            raise ValueError("start_hour_utc must be between 0 and 23")
        if not 1 <= self.end_hour_utc <= 24:
            raise ValueError("end_hour_utc must be between 1 and 24")

    def rejection_reason(self, timestamp: datetime, spread_points: float | None) -> str | None:
        hour = timestamp.hour
        if self.start_hour_utc < self.end_hour_utc:
            in_session = self.start_hour_utc <= hour < self.end_hour_utc
        elif self.start_hour_utc > self.end_hour_utc:
            in_session = hour >= self.start_hour_utc or hour < self.end_hour_utc
        else:
            in_session = False
        if not in_session:
            return "outside_trading_hours"
        if self.max_spread_points is not None:
            if spread_points is None:
                return "spread_unavailable"
            if spread_points > self.max_spread_points:
                return "spread_limit_exceeded"
        return None
