"""Read-only MetaTrader 5 terminal adapter.

The adapter intentionally exposes market-data operations only. Order execution is
added later as a separately reviewed component.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

from forexbot.domain import Candle


class MT5ConnectionError(RuntimeError):
    """Raised when the local MetaTrader 5 terminal cannot be used."""


class MT5MarketData:
    def __init__(
        self,
        terminal_path: Path | None = None,
        client: ModuleType | None = None,
        server_utc_offset_hours: float | None = None,
    ) -> None:
        self.terminal_path = terminal_path
        self._client = client
        self._server_utc_offset_seconds = (
            round(server_utc_offset_hours * 3600) if server_utc_offset_hours is not None else None
        )

    @property
    def server_utc_offset_seconds(self) -> int | None:
        return self._server_utc_offset_seconds

    def connect(self) -> None:
        client = self._get_client()
        arguments = {"path": str(self.terminal_path)} if self.terminal_path else {}
        if not client.initialize(**arguments):
            raise MT5ConnectionError(f"MT5 initialization failed: {client.last_error()}")

    def disconnect(self) -> None:
        self._get_client().shutdown()

    def fetch_candles(self, symbol: str, timeframe: str, count: int) -> list[Candle]:
        if count < 2:
            raise ValueError("count must be at least 2")
        client = self._get_client()
        timeframe_code = self._timeframe_code(timeframe)
        if not client.symbol_select(symbol, True):
            raise MT5ConnectionError(f"Unable to select symbol {symbol}: {client.last_error()}")
        rates = client.copy_rates_from_pos(symbol, timeframe_code, 1, count)
        if rates is None or len(rates) < 2:
            raise MT5ConnectionError(f"Unable to load candles for {symbol}: {client.last_error()}")
        offset_seconds = self._get_server_utc_offset_seconds(symbol)
        candles = [
            Candle(
                timestamp=datetime.fromtimestamp(int(rate["time"]) - offset_seconds, tz=UTC),
                open=float(rate["open"]),
                high=float(rate["high"]),
                low=float(rate["low"]),
                close=float(rate["close"]),
            )
            for rate in rates
        ]
        if any(current.timestamp <= previous.timestamp for previous, current in zip(candles, candles[1:])):
            raise MT5ConnectionError(f"MT5 returned unordered or duplicate candles for {symbol}")
        return candles

    def _get_server_utc_offset_seconds(self, symbol: str) -> int:
        if self._server_utc_offset_seconds is not None:
            return self._server_utc_offset_seconds
        client = self._get_client()
        tick_reader = getattr(client, "symbol_info_tick", None)
        if tick_reader is None:
            self._server_utc_offset_seconds = 0
            return 0
        tick = tick_reader(symbol)
        if tick is None:
            raise MT5ConnectionError(f"Unable to determine MT5 server time offset: {client.last_error()}")
        difference = int(tick.time) - int(datetime.now(UTC).timestamp())
        nearest_hour = round(difference / 3600) * 3600
        if abs(difference) <= 180:
            nearest_hour = 0
        elif not -14 * 3600 <= nearest_hour <= 14 * 3600 or abs(difference - nearest_hour) > 180:
            raise MT5ConnectionError(
                "MT5 tick time does not match UTC or a whole-hour server offset; refusing to normalize timestamps"
            )
        self._server_utc_offset_seconds = nearest_hour
        return nearest_hour

    def spread_points(self, symbol: str) -> float:
        quote = self.fetch_quote(symbol)
        return float(quote["spread_points"])

    def fetch_quote(self, symbol: str) -> dict[str, float | str]:
        client = self._get_client()
        if not client.symbol_select(symbol, True):
            raise MT5ConnectionError(f"Unable to select symbol {symbol}: {client.last_error()}")
        symbol_info = client.symbol_info(symbol)
        tick = client.symbol_info_tick(symbol)
        if symbol_info is None or tick is None or symbol_info.point <= 0 or tick.bid <= 0 or tick.ask < tick.bid:
            raise MT5ConnectionError(f"Unable to read a valid quote for {symbol}: {client.last_error()}")
        offset_seconds = self._get_server_utc_offset_seconds(symbol)
        return {
            "bid": float(tick.bid),
            "ask": float(tick.ask),
            "spread_points": (float(tick.ask) - float(tick.bid)) / float(symbol_info.point),
            "timestamp": datetime.fromtimestamp(int(tick.time) - offset_seconds, tz=UTC).isoformat(),
        }

    def _timeframe_code(self, timeframe: str) -> int:
        client = self._get_client()
        timeframe_name = f"TIMEFRAME_{timeframe.upper()}"
        try:
            return getattr(client, timeframe_name)
        except AttributeError as error:
            raise ValueError(f"Unsupported MT5 timeframe: {timeframe}") from error

    def _get_client(self) -> ModuleType:
        if self._client is None:
            try:
                import MetaTrader5 as client
            except ImportError as error:
                raise MT5ConnectionError(
                    "MetaTrader5 is not installed. Install with: pip install -e .[mt5]"
                ) from error
            self._client = client
        return self._client
