from dataclasses import dataclass
from math import inf
from typing import Protocol

from forexbot.domain import Candle, Signal, Trade
from forexbot.risk import RiskManager


class Strategy(Protocol):
    def signal(self, candles: list[Candle]) -> Signal | None: ...


@dataclass(frozen=True)
class BacktestResult:
    trades: list[Trade]
    starting_balance: float

    @property
    def net_profit(self) -> float:
        return sum(trade.profit_loss for trade in self.trades)

    @property
    def ending_balance(self) -> float:
        return self.starting_balance + self.net_profit

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return sum(trade.profit_loss > 0 for trade in self.trades) / len(self.trades)

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(trade.profit_loss for trade in self.trades if trade.profit_loss > 0)
        gross_loss = -sum(trade.profit_loss for trade in self.trades if trade.profit_loss < 0)
        if gross_loss == 0:
            return inf if gross_profit else 0.0
        return gross_profit / gross_loss

    @property
    def max_drawdown(self) -> float:
        balance = self.starting_balance
        peak = balance
        maximum = 0.0
        for trade in self.trades:
            balance += trade.profit_loss
            peak = max(peak, balance)
            maximum = max(maximum, peak - balance)
        return maximum

    @property
    def return_percentage(self) -> float:
        return self.net_profit / self.starting_balance if self.starting_balance else 0.0


class Backtester:
    def __init__(
        self,
        strategy: Strategy,
        risk_manager: RiskManager,
        starting_balance: float,
        slippage: float = 0.0,
        commission_per_unit: float = 0.0,
    ) -> None:
        if slippage < 0 or commission_per_unit < 0:
            raise ValueError("slippage and commission_per_unit cannot be negative")
        self.strategy = strategy
        self.risk_manager = risk_manager
        self.starting_balance = starting_balance
        self.slippage = slippage
        self.commission_per_unit = commission_per_unit

    def run(self, candles: list[Candle]) -> BacktestResult:
        trades: list[Trade] = []
        balance = self.starting_balance
        peak_balance = balance
        daily_loss = 0.0
        active_date = None
        for index in range(1, len(candles) - 1):
            history = candles[: index + 1]
            trade_date = history[-1].timestamp.date()
            if trade_date != active_date:
                daily_loss = 0.0
                active_date = trade_date
            signal = self.strategy.signal(history)
            if signal is None:
                continue
            entry = self._entry_price(signal, candles[index + 1].open)
            drawdown = (peak_balance - balance) / peak_balance if peak_balance else 0.0
            units = self.risk_manager.approve(signal, entry, 0, daily_loss, balance, drawdown)
            if units is None:
                continue
            exit_price = self._exit_price(signal, candles[index + 1])
            commission = units * self.commission_per_unit
            trade = Trade(signal.side, entry, exit_price, units, commission)
            trades.append(trade)
            daily_loss += max(0, -trade.profit_loss)
            balance += trade.profit_loss
            peak_balance = max(peak_balance, balance)
        return BacktestResult(trades, self.starting_balance)

    def _entry_price(self, signal: Signal, price: float) -> float:
        return price + self.slippage if signal.side.value == "buy" else price - self.slippage

    def _exit_price(self, signal: Signal, candle: Candle) -> float:
        if signal.side.value == "buy":
            if candle.low <= signal.stop_loss:
                return signal.stop_loss - self.slippage
            if candle.high >= signal.take_profit:
                return signal.take_profit - self.slippage
            return candle.close - self.slippage
        else:
            if candle.high >= signal.stop_loss:
                return signal.stop_loss + self.slippage
            if candle.low <= signal.take_profit:
                return signal.take_profit + self.slippage
            return candle.close + self.slippage
