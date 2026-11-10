from dataclasses import dataclass
from math import isfinite

from forexbot.domain import Side, Signal


@dataclass(frozen=True)
class RiskLimits:
    account_balance: float = 10_000.0
    risk_per_trade: float = 0.01
    max_daily_loss: float = 0.03
    max_drawdown: float = 0.10
    max_open_trades: int = 1


class RiskManager:
    def __init__(self, limits: RiskLimits) -> None:
        if not isfinite(limits.account_balance) or limits.account_balance <= 0:
            raise ValueError("account_balance must be positive")
        if not isfinite(limits.risk_per_trade) or not 0 < limits.risk_per_trade <= 1:
            raise ValueError("risk_per_trade must be between zero and one")
        if not isfinite(limits.max_daily_loss) or not 0 < limits.max_daily_loss <= 1:
            raise ValueError("max_daily_loss must be between zero and one")
        if not isfinite(limits.max_drawdown) or not 0 < limits.max_drawdown <= 1:
            raise ValueError("max_drawdown must be between zero and one")
        if limits.max_open_trades < 1:
            raise ValueError("max_open_trades must be at least one")
        self.limits = limits

    def approve(
        self,
        signal: Signal,
        entry_price: float,
        open_trades: int,
        daily_loss: float,
        current_balance: float | None = None,
        drawdown: float = 0.0,
    ) -> float | None:
        balance = current_balance if current_balance is not None else self.limits.account_balance
        if not all(isfinite(value) for value in (entry_price, balance, daily_loss, drawdown)):
            return None
        if entry_price <= 0 or balance <= 0 or daily_loss < 0 or drawdown < 0:
            return None
        if open_trades >= self.limits.max_open_trades:
            return None
        if daily_loss >= balance * self.limits.max_daily_loss:
            return None
        if drawdown >= self.limits.max_drawdown:
            return None
        if not isfinite(signal.stop_loss) or not isfinite(signal.take_profit):
            return None
        if signal.side is Side.BUY:
            valid_levels = signal.stop_loss < entry_price < signal.take_profit
        else:
            valid_levels = signal.take_profit < entry_price < signal.stop_loss
        if not valid_levels:
            return None
        risk_distance = abs(entry_price - signal.stop_loss)
        risk_amount = balance * self.limits.risk_per_trade
        return risk_amount / risk_distance
