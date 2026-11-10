import csv
from datetime import datetime
from io import StringIO
from pathlib import Path

from forexbot.domain import Candle


def load_candles_csv(path: Path) -> list[Candle]:
    """Load OHLC candles from a CSV with timestamp,open,high,low,close headers."""
    return parse_candles_csv(path.read_text(encoding="utf-8"))


def parse_candles_csv(contents: str) -> list[Candle]:
    rows = csv.DictReader(StringIO(contents))
    required_columns = {"timestamp", "open", "high", "low", "close"}
    if not rows.fieldnames or not required_columns.issubset(rows.fieldnames):
        raise ValueError("CSV must contain timestamp,open,high,low,close columns")
    try:
        candles = [
            Candle(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
            )
            for row in rows
        ]
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid candle row: {error}") from error
    if len(candles) < 2:
        raise ValueError("At least two candles are required")
    return candles
