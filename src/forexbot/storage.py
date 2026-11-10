"""Local SQLite storage for backtest run history."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from forexbot.backtest import BacktestResult
from forexbot.domain import Candle, Side
from forexbot.paper import PaperFill


@dataclass(frozen=True)
class BacktestRun:
    source: str
    symbol: str
    timeframe: str
    candle_count: int
    result: BacktestResult


class BacktestStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    candle_count INTEGER NOT NULL,
                    trade_count INTEGER NOT NULL,
                    net_profit REAL NOT NULL,
                    ending_balance REAL NOT NULL,
                    win_rate REAL NOT NULL,
                    profit_factor REAL NOT NULL,
                    max_drawdown REAL NOT NULL
                )
                """
            )

    def save_run(self, run: BacktestRun) -> int:
        self.initialize()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO backtest_runs (
                    created_at, source, symbol, timeframe, candle_count, trade_count,
                    net_profit, ending_balance, win_rate, profit_factor, max_drawdown
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(UTC).isoformat(),
                    run.source,
                    run.symbol,
                    run.timeframe,
                    run.candle_count,
                    len(run.result.trades),
                    run.result.net_profit,
                    run.result.ending_balance,
                    run.result.win_rate,
                    run.result.profit_factor,
                    run.result.max_drawdown,
                ),
            )
            return int(cursor.lastrowid)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    def recent_runs(self, limit: int = 20) -> list[dict[str, object]]:
        if limit < 1:
            raise ValueError("limit must be positive")
        if not self.database_path.exists():
            return []
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT * FROM backtest_runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]


class PaperStateStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_fills (
                    client_order_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    units REAL NOT NULL,
                    fill_price REAL NOT NULL,
                    created_at TEXT NOT NULL DEFAULT '',
                    stop_loss REAL,
                    take_profit REAL,
                    exit_price REAL,
                    profit_loss REAL NOT NULL DEFAULT 0,
                    closed_at TEXT
                )
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(paper_fills)")}
            if "created_at" not in columns:
                connection.execute("ALTER TABLE paper_fills ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
            migrations = {
                "stop_loss": "REAL",
                "take_profit": "REAL",
                "exit_price": "REAL",
                "profit_loss": "REAL NOT NULL DEFAULT 0",
                "closed_at": "TEXT",
            }
            for column, column_type in migrations.items():
                if column not in columns:
                    connection.execute(f"ALTER TABLE paper_fills ADD COLUMN {column} {column_type}")

    def save_fill(self, fill: PaperFill) -> None:
        self.initialize()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO paper_fills (
                    client_order_id, symbol, side, units, fill_price, created_at,
                    stop_loss, take_profit
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fill.client_order_id,
                    fill.symbol,
                    fill.side.value,
                    fill.units,
                    fill.fill_price,
                    datetime.now(UTC).isoformat(),
                    fill.stop_loss,
                    fill.take_profit,
                ),
            )

    def load_fills(self) -> list[PaperFill]:
        if not self.database_path.exists():
            return []
        self.initialize()
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                """SELECT client_order_id, symbol, side, units, fill_price, stop_loss,
                take_profit, exit_price, profit_loss, closed_at FROM paper_fills"""
            ).fetchall()
        return [
            PaperFill(
                row[0], row[1], Side(row[2]), row[3], row[4], False,
                row[5], row[6], row[7], row[8], row[9],
            )
            for row in rows
        ]

    def daily_loss(self, session_date) -> float:
        self.initialize()
        start = datetime.combine(session_date, datetime.min.time(), tzinfo=UTC).isoformat()
        end = datetime.combine(session_date, datetime.max.time(), tzinfo=UTC).isoformat()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT COALESCE(-SUM(profit_loss), 0) FROM paper_fills WHERE closed_at >= ? AND closed_at <= ? AND profit_loss < 0",
                (start, end),
            ).fetchone()
        return float(row[0])

    def open_fills(self, symbol: str | None = None) -> list[PaperFill]:
        fills = self.load_fills()
        return [fill for fill in fills if fill.closed_at is None and (symbol is None or fill.symbol == symbol)]

    def close_positions(self, symbol: str, candle: Candle, slippage: float = 0.0) -> list[PaperFill]:
        self.initialize()
        closed: list[PaperFill] = []
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                """SELECT client_order_id, symbol, side, units, fill_price, stop_loss, take_profit
                FROM paper_fills WHERE symbol = ? AND closed_at IS NULL""",
                (symbol,),
            ).fetchall()
            for row in rows:
                side = Side(row[2])
                stop_loss, take_profit = row[5], row[6]
                exit_price = self._exit_price(side, stop_loss, take_profit, candle, slippage)
                if exit_price is None:
                    continue
                direction = 1 if side is Side.BUY else -1
                profit_loss = (exit_price - row[4]) * row[3] * direction
                closed_at = candle.timestamp.astimezone(UTC).isoformat()
                connection.execute(
                    """UPDATE paper_fills SET exit_price = ?, profit_loss = ?, closed_at = ?
                    WHERE client_order_id = ? AND closed_at IS NULL""",
                    (exit_price, profit_loss, closed_at, row[0]),
                )
                closed.append(PaperFill(row[0], row[1], side, row[3], row[4], False, stop_loss, take_profit, exit_price, profit_loss, closed_at))
        return closed

    def realized_profit(self) -> float:
        if not self.database_path.exists():
            return 0.0
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute("SELECT COALESCE(SUM(profit_loss), 0) FROM paper_fills WHERE closed_at IS NOT NULL").fetchone()
        return float(row[0])

    def dashboard_summary(self) -> dict[str, object]:
        if not self.database_path.exists():
            return {
                "realized_profit": 0.0,
                "open_positions": [],
                "performance": self._performance_summary([]),
                "recent_closed_trades": [],
            }
        self.initialize()
        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """SELECT symbol, side, units, fill_price, stop_loss, take_profit, created_at
                FROM paper_fills WHERE closed_at IS NULL ORDER BY created_at DESC"""
            ).fetchall()
            closed_rows = connection.execute(
                """SELECT symbol, side, units, fill_price, exit_price, profit_loss, closed_at
                FROM paper_fills WHERE closed_at IS NOT NULL ORDER BY closed_at, rowid"""
            ).fetchall()
        closed_trades = [dict(row) for row in closed_rows]
        return {
            "realized_profit": sum(float(trade["profit_loss"]) for trade in closed_trades),
            "open_positions": [dict(row) for row in rows],
            "performance": self._performance_summary(closed_trades),
            "recent_closed_trades": list(reversed(closed_trades[-10:])),
        }

    @staticmethod
    def _performance_summary(closed_trades: list[dict[str, object]]) -> dict[str, object]:
        profits = [float(trade["profit_loss"]) for trade in closed_trades]
        gross_profit = sum(profit for profit in profits if profit > 0)
        gross_loss = -sum(profit for profit in profits if profit < 0)
        balance = peak = 10_000.0
        maximum_drawdown = 0.0
        for profit in profits:
            balance += profit
            peak = max(peak, balance)
            if peak > 0:
                maximum_drawdown = max(maximum_drawdown, (peak - balance) / peak)
        trade_count = len(profits)
        winning_trades = sum(profit > 0 for profit in profits)
        return {
            "closed_trade_count": trade_count,
            "winning_trades": winning_trades,
            "losing_trades": sum(profit < 0 for profit in profits),
            "win_rate": winning_trades / trade_count if trade_count else 0.0,
            "profit_factor": gross_profit / gross_loss if gross_loss else None,
            "max_drawdown": maximum_drawdown,
        }

    def max_realized_drawdown(self, starting_balance: float) -> float:
        if not self.database_path.exists():
            return 0.0
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT profit_loss FROM paper_fills WHERE closed_at IS NOT NULL ORDER BY closed_at, rowid"
            ).fetchall()
        balance = peak = starting_balance
        maximum = 0.0
        for (profit_loss,) in rows:
            balance += profit_loss
            peak = max(peak, balance)
            if peak > 0:
                maximum = max(maximum, (peak - balance) / peak)
        return maximum

    def last_processed_candle(self, symbol: str, timeframe: str) -> datetime | None:
        self.initialize()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS paper_cursors (
                symbol TEXT NOT NULL, timeframe TEXT NOT NULL, candle_time TEXT NOT NULL,
                PRIMARY KEY (symbol, timeframe))"""
            )
            row = connection.execute(
                "SELECT candle_time FROM paper_cursors WHERE symbol = ? AND timeframe = ?",
                (symbol, timeframe),
            ).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def save_processed_candle(self, symbol: str, timeframe: str, candle_time: datetime) -> None:
        self.initialize()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS paper_cursors (
                symbol TEXT NOT NULL, timeframe TEXT NOT NULL, candle_time TEXT NOT NULL,
                PRIMARY KEY (symbol, timeframe))"""
            )
            connection.execute(
                """INSERT INTO paper_cursors (symbol, timeframe, candle_time) VALUES (?, ?, ?)
                ON CONFLICT(symbol, timeframe) DO UPDATE SET candle_time = excluded.candle_time""",
                (symbol, timeframe, candle_time.astimezone(UTC).isoformat()),
            )

    def shift_processed_candle(self, symbol: str, timeframe: str, seconds: int) -> None:
        self.initialize()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS paper_cursors (
                symbol TEXT NOT NULL, timeframe TEXT NOT NULL, candle_time TEXT NOT NULL,
                PRIMARY KEY (symbol, timeframe))"""
            )
            row = connection.execute(
                "SELECT candle_time FROM paper_cursors WHERE symbol = ? AND timeframe = ?",
                (symbol, timeframe),
            ).fetchone()
            if row:
                shifted = datetime.fromisoformat(row[0]) - timedelta(seconds=seconds)
                connection.execute(
                    "UPDATE paper_cursors SET candle_time = ? WHERE symbol = ? AND timeframe = ?",
                    (shifted.astimezone(UTC).isoformat(), symbol, timeframe),
                )

    @staticmethod
    def _exit_price(side: Side, stop_loss: float | None, take_profit: float | None, candle: Candle, slippage: float) -> float | None:
        if stop_loss is None or take_profit is None:
            return None
        if side is Side.BUY:
            if candle.low <= stop_loss:
                return stop_loss - slippage
            if candle.high >= take_profit:
                return take_profit - slippage
        else:
            if candle.high >= stop_loss:
                return stop_loss + slippage
            if candle.low <= take_profit:
                return take_profit + slippage
        return None
