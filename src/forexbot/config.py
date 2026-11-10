"""Configuration loading and validation."""

from dataclasses import dataclass
from pathlib import Path
import tomllib

from forexbot.risk import RiskLimits
from forexbot.filters import TradingFilters


@dataclass(frozen=True)
class BotSettings:
    mode: str
    risk_limits: RiskLimits
    trading_filters: TradingFilters
    server_utc_offset_hours: float | None


def load_settings(path: Path) -> BotSettings:
    with path.open("rb") as config_file:
        config = tomllib.load(config_file)
    bot = config.get("bot", {})
    risk = config.get("risk", {})
    filters = config.get("filters", {})
    mt5 = config.get("mt5", {})
    mode = str(bot.get("mode", "backtest")).lower()
    if mode not in {"backtest", "demo", "live"}:
        raise ValueError("bot.mode must be backtest, demo, or live")
    limits = RiskLimits(
        account_balance=float(risk.get("account_balance", 10_000.0)),
        risk_per_trade=float(risk.get("risk_per_trade", 0.01)),
        max_daily_loss=float(risk.get("max_daily_loss", 0.03)),
        max_drawdown=float(risk.get("max_drawdown", 0.10)),
        max_open_trades=int(risk.get("max_open_trades", 1)),
    )
    trading_filters = TradingFilters(
        max_spread_points=float(filters.get("max_spread_points", 30.0)),
        start_hour_utc=int(filters.get("start_hour_utc", 0)),
        end_hour_utc=int(filters.get("end_hour_utc", 24)),
    )
    server_offset = mt5.get("server_utc_offset_hours", "auto")
    server_utc_offset_hours = None if str(server_offset).lower() == "auto" else float(server_offset)
    if server_utc_offset_hours is not None and abs(server_utc_offset_hours) > 14:
        raise ValueError("mt5.server_utc_offset_hours must be between -14 and 14, or 'auto'")
    return BotSettings(mode, limits, trading_filters, server_utc_offset_hours)
