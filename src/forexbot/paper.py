"""Idempotent, demo-only order simulation.

This module deliberately has no broker dependency and cannot submit live orders.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
import logging

from forexbot.audit import log_event
from forexbot.domain import Side


@dataclass(frozen=True)
class PaperOrder:
    client_order_id: str
    symbol: str
    side: Side
    units: float
    requested_price: float
    stop_loss: float | None = None
    take_profit: float | None = None


@dataclass(frozen=True)
class PaperFill:
    client_order_id: str
    symbol: str
    side: Side
    units: float
    fill_price: float
    duplicate: bool = False
    stop_loss: float | None = None
    take_profit: float | None = None
    exit_price: float | None = None
    profit_loss: float = 0.0
    closed_at: str | None = None


class PaperExecutor:
    def __init__(
        self,
        slippage: float = 0.0,
        audit_logger: logging.Logger | None = None,
        existing_fills: Iterable[PaperFill] = (),
        save_fill: Callable[[PaperFill], None] | None = None,
    ) -> None:
        if slippage < 0:
            raise ValueError("slippage cannot be negative")
        self.slippage = slippage
        self.audit_logger = audit_logger
        self._fills = {fill.client_order_id: fill for fill in existing_fills}
        self.save_fill = save_fill

    def submit(self, order: PaperOrder) -> PaperFill:
        if not order.client_order_id.strip():
            raise ValueError("client_order_id is required")
        if not order.symbol.strip():
            raise ValueError("symbol is required")
        if order.units <= 0 or order.requested_price <= 0:
            raise ValueError("units and requested_price must be positive")
        if (order.stop_loss is None) != (order.take_profit is None):
            raise ValueError("stop_loss and take_profit must be provided together")
        if order.stop_loss is not None and order.take_profit is not None:
            if order.stop_loss <= 0 or order.take_profit <= 0:
                raise ValueError("stop_loss and take_profit must be positive")
            if order.side is Side.BUY and not order.stop_loss < order.requested_price < order.take_profit:
                raise ValueError("buy orders require stop_loss < requested_price < take_profit")
            if order.side is Side.SELL and not order.take_profit < order.requested_price < order.stop_loss:
                raise ValueError("sell orders require take_profit < requested_price < stop_loss")
        existing = self._fills.get(order.client_order_id)
        if existing:
            duplicate = replace(existing, duplicate=True)
            log_event(self.audit_logger, "paper_order_duplicate", client_order_id=order.client_order_id)
            return duplicate
        direction = 1 if order.side is Side.BUY else -1
        fill = PaperFill(
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            units=order.units,
            fill_price=order.requested_price + direction * self.slippage,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
        )
        if self.save_fill is not None:
            self.save_fill(fill)
        self._fills[order.client_order_id] = fill
        log_event(
            self.audit_logger,
            "paper_order_filled",
            client_order_id=fill.client_order_id,
            symbol=fill.symbol,
            side=fill.side.value,
            units=fill.units,
            fill_price=fill.fill_price,
        )
        return fill

    def restore_fills(self, fills: Iterable[PaperFill]) -> None:
        self._fills = {fill.client_order_id: fill for fill in fills}
