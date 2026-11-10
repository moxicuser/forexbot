"""Restart-safe polling loop that creates simulated paper fills from MT5 candles."""

import logging
from datetime import UTC, datetime

from forexbot.alerts import Alerter, NullAlerter
from forexbot.audit import log_event
from forexbot.domain import Candle, Signal
from forexbot.filters import TradingFilters
from forexbot.mt5 import MT5MarketData
from forexbot.paper import PaperExecutor, PaperOrder
from forexbot.risk import RiskManager
from forexbot.storage import PaperStateStore
from forexbot.strategy import MovingAverageCrossover


class PaperSession:
    def __init__(
        self,
        market_data: MT5MarketData,
        strategy: MovingAverageCrossover,
        risk_manager: RiskManager,
        state_store: PaperStateStore,
        executor: PaperExecutor,
        symbol: str,
        timeframe: str,
        candle_count: int = 100,
        poll_seconds: float = 5.0,
        audit_logger: logging.Logger | None = None,
        trading_filters: TradingFilters | None = None,
        alerter: Alerter | None = None,
    ) -> None:
        if candle_count < strategy.slow_period + 1:
            raise ValueError("candle_count must cover the strategy lookback")
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self.market_data = market_data
        self.strategy = strategy
        self.risk_manager = risk_manager
        self.state_store = state_store
        self.executor = executor
        self.symbol = symbol
        self.timeframe = timeframe.upper()
        self.candle_count = candle_count
        self.poll_seconds = poll_seconds
        self.audit_logger = audit_logger
        self.trading_filters = trading_filters or TradingFilters()
        self.alerter = alerter or NullAlerter()

    def run_once(self) -> bool:
        candles = self.market_data.fetch_candles(self.symbol, self.timeframe, self.candle_count)
        cursor = self.state_store.last_processed_candle(self.symbol, self.timeframe)
        offset_seconds = self.market_data.server_utc_offset_seconds
        if cursor is not None and offset_seconds:
            cursor_ahead = (cursor - candles[-1].timestamp).total_seconds()
            if abs(cursor_ahead - offset_seconds) <= 180:
                self.state_store.shift_processed_candle(self.symbol, self.timeframe, offset_seconds)
                cursor = self.state_store.last_processed_candle(self.symbol, self.timeframe)
        if cursor is None:
            pending = [(len(candles) - 1, candles[-1])]
        else:
            pending = [(index, candle) for index, candle in enumerate(candles) if candle.timestamp > cursor]
        if not pending:
            log_event(
                self.audit_logger,
                "paper_session_poll",
                symbol=self.symbol,
                timeframe=self.timeframe,
            )
            return False
        for index, candle in pending:
            closed = self.state_store.close_positions(self.symbol, candle, self.executor.slippage)
            for fill in closed:
                log_event(
                    self.audit_logger,
                    "paper_position_closed",
                    client_order_id=fill.client_order_id,
                    exit_price=fill.exit_price,
                    profit_loss=fill.profit_loss,
                )
                self._send_alert(
                    "position_closed",
                    {"symbol": fill.symbol, "profit_loss": f"{fill.profit_loss:.2f}"},
                )
            history = candles[: index + 1]
            signal = self.strategy.signal(history)
            log_event(
                self.audit_logger,
                "paper_session_heartbeat",
                symbol=self.symbol,
                timeframe=self.timeframe,
                candle_time=candle.timestamp.isoformat(),
                signal=signal.side.value if signal else None,
                server_utc_offset_seconds=self.market_data.server_utc_offset_seconds,
            )
            if signal is not None:
                client_order_id = self._signal_id(candle, signal)
                existing_fills = self.state_store.load_fills()
                if any(fill.client_order_id == client_order_id for fill in existing_fills):
                    log_event(self.audit_logger, "paper_signal_already_processed", client_order_id=client_order_id)
                else:
                    spread_points = self.market_data.spread_points(self.symbol)
                    rejection = self.trading_filters.rejection_reason(candle.timestamp, spread_points)
                    if rejection:
                        log_event(
                            self.audit_logger,
                            "paper_signal_filtered",
                            client_order_id=client_order_id,
                            reason=rejection,
                            spread_points=spread_points,
                        )
                        self._send_alert(
                            "signal_filtered",
                            {"symbol": self.symbol, "reason": rejection},
                        )
                        self.state_store.save_processed_candle(self.symbol, self.timeframe, candle.timestamp)
                        continue
                    daily_loss = self.state_store.daily_loss(candle.timestamp.date())
                    open_trades = len(self.state_store.open_fills())
                    balance = self.risk_manager.limits.account_balance + self.state_store.realized_profit()
                    drawdown = self.state_store.max_realized_drawdown(self.risk_manager.limits.account_balance)
                    units = self.risk_manager.approve(signal, candle.close, open_trades, daily_loss, balance, drawdown)
                    if units is None:
                        log_event(
                            self.audit_logger,
                            "paper_signal_blocked_by_risk",
                            client_order_id=client_order_id,
                            open_trades=open_trades,
                            daily_loss=daily_loss,
                            drawdown=drawdown,
                        )
                        self._send_alert(
                            "risk_blocked",
                            {"symbol": self.symbol, "reason": "risk limits reached"},
                        )
                    else:
                        fill = self.executor.submit(
                            PaperOrder(
                                client_order_id,
                                self.symbol,
                                signal.side,
                                units,
                                candle.close,
                                signal.stop_loss,
                                signal.take_profit,
                            )
                        )
                        self._send_alert(
                            "position_opened",
                            {
                                "symbol": fill.symbol,
                                "side": fill.side.value,
                                "units": f"{fill.units:.2f}",
                                "entry": f"{fill.fill_price:.5f}",
                                "stop_loss": f"{signal.stop_loss:.5f}",
                                "take_profit": f"{signal.take_profit:.5f}",
                            },
                        )
            self.state_store.save_processed_candle(self.symbol, self.timeframe, candle.timestamp)
        return True

    def run_forever(self, stop_event) -> None:
        fills = self.state_store.load_fills()
        self.executor.restore_fills(fills)
        log_event(self.audit_logger, "paper_session_started", symbol=self.symbol, timeframe=self.timeframe)
        try:
            while not stop_event.is_set():
                try:
                    self.run_once()
                except Exception as error:
                    log_event(
                        self.audit_logger,
                        "paper_session_error",
                        error_type=type(error).__name__,
                        error=str(error),
                    )
                    self._send_alert(
                        "session_error",
                        {"type": type(error).__name__, "message": str(error)[:300]},
                    )
                    try:
                        self.market_data.disconnect()
                        self.market_data.connect()
                    except Exception as reconnect_error:
                        log_event(
                            self.audit_logger,
                            "paper_session_reconnect_failed",
                            error_type=type(reconnect_error).__name__,
                            error=str(reconnect_error),
                        )
                        self._send_alert(
                            "terminal_reconnect_failed",
                            {"type": type(reconnect_error).__name__},
                        )
                stop_event.wait(self.poll_seconds)
        finally:
            log_event(self.audit_logger, "paper_session_stopped", symbol=self.symbol, timeframe=self.timeframe)

    @staticmethod
    def _signal_id(candle: Candle, signal: Signal) -> str:
        normalized_time = candle.timestamp.astimezone(UTC).isoformat()
        return f"{signal.side.value}:{normalized_time}"

    def _send_alert(self, event: str, details: dict[str, object]) -> None:
        try:
            self.alerter.send(event, details)
        except Exception as error:
            log_event(
                self.audit_logger,
                "alert_delivery_failed",
                alert_event=event,
                error_type=type(error).__name__,
                error=str(error)[:300],
            )
