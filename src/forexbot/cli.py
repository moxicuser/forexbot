import argparse
from threading import Event
from pathlib import Path

from forexbot.backtest import Backtester
from forexbot.alerts import create_alerter
from forexbot.audit import configure_audit_logger
from forexbot.config import load_settings
from forexbot.data import load_candles_csv
from forexbot.filters import TradingFilters
from forexbot.mt5 import MT5ConnectionError, MT5MarketData
from forexbot.risk import RiskLimits, RiskManager
from forexbot.paper import PaperExecutor
from forexbot.session import PaperSession
from forexbot.storage import BacktestRun, BacktestStore, PaperStateStore
from forexbot.strategy import MovingAverageCrossover


def main() -> None:
    parser = argparse.ArgumentParser(description="ForexBot research CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    backtest = subparsers.add_parser("backtest", help="Run a CSV backtest")
    backtest.add_argument("csv_path", type=Path)
    _add_cost_arguments(backtest)
    _add_storage_arguments(backtest)
    _add_config_argument(backtest)
    status = subparsers.add_parser("mt5-status", help="Check the local MT5 terminal")
    status.add_argument("--terminal-path", type=Path)
    paper = subparsers.add_parser("paper-session", help="Run the simulated MT5 paper session")
    paper.add_argument("symbol")
    paper.add_argument("--timeframe", default="M15")
    paper.add_argument("--count", type=int, default=100)
    paper.add_argument("--poll-seconds", type=float, default=5.0)
    paper.add_argument("--slippage", type=float, default=0.0)
    paper.add_argument("--terminal-path", type=Path)
    paper.add_argument("--config", type=Path)
    paper.add_argument("--database", type=Path, default=Path("data/forexbot.db"))
    paper.add_argument("--log", type=Path, default=Path("logs/paper-session.jsonl"))
    mt5_backtest = subparsers.add_parser("mt5-backtest", help="Backtest using candles from the local MT5 terminal")
    mt5_backtest.add_argument("symbol")
    mt5_backtest.add_argument("--timeframe", default="M15")
    mt5_backtest.add_argument("--count", type=int, default=2_000)
    mt5_backtest.add_argument("--terminal-path", type=Path)
    _add_cost_arguments(mt5_backtest)
    _add_storage_arguments(mt5_backtest)
    _add_config_argument(mt5_backtest)
    arguments = parser.parse_args()

    if arguments.command == "backtest":
        candles = load_candles_csv(arguments.csv_path)
        limits = _risk_limits_from_arguments(arguments)
        result = _run_backtest(candles, limits, arguments.slippage, arguments.commission_per_unit)
        _print_result(result)
        _save_result(arguments, result, "csv", arguments.csv_path.stem, "unknown", len(candles))
    if arguments.command == "mt5-status":
        market_data = MT5MarketData(arguments.terminal_path)
        try:
            market_data.connect()
            print("MT5 terminal connection verified.")
        except MT5ConnectionError as error:
            raise SystemExit(str(error)) from error
        finally:
            market_data.disconnect()
    if arguments.command == "mt5-backtest":
        settings = load_settings(arguments.config) if arguments.config else None
        if settings and settings.mode == "live":
            raise SystemExit("Live mode is not implemented. Use backtest or demo mode.")
        market_data = MT5MarketData(
            arguments.terminal_path,
            server_utc_offset_hours=settings.server_utc_offset_hours if settings else None,
        )
        try:
            market_data.connect()
            candles = market_data.fetch_candles(arguments.symbol, arguments.timeframe, arguments.count)
        except MT5ConnectionError as error:
            raise SystemExit(str(error)) from error
        finally:
            market_data.disconnect()
        limits = settings.risk_limits if settings else RiskLimits()
        result = _run_backtest(candles, limits, arguments.slippage, arguments.commission_per_unit)
        print(f"Source: MT5 {arguments.symbol} {arguments.timeframe} ({len(candles)} candles)")
        _print_result(result)
        _save_result(arguments, result, "mt5", arguments.symbol, arguments.timeframe, len(candles))
    if arguments.command == "paper-session":
        _run_paper_session(arguments)


def _run_paper_session(arguments) -> None:
    settings = load_settings(arguments.config) if arguments.config else None
    if settings and settings.mode == "live":
        raise SystemExit("Live mode is not implemented. Use backtest or demo mode.")
    limits = settings.risk_limits if settings else RiskLimits()
    trading_filters = settings.trading_filters if settings else TradingFilters()
    if arguments.count < 31:
        raise SystemExit("--count must be at least 31 for the default strategy")
    if arguments.poll_seconds <= 0:
        raise SystemExit("--poll-seconds must be positive")
    state_store = PaperStateStore(arguments.database)
    state_store.initialize()
    logger = configure_audit_logger(arguments.log)
    executor = PaperExecutor(
        slippage=arguments.slippage,
        audit_logger=logger,
        existing_fills=state_store.load_fills(),
        save_fill=state_store.save_fill,
    )
    session = PaperSession(
        MT5MarketData(
            arguments.terminal_path,
            server_utc_offset_hours=settings.server_utc_offset_hours if settings else None,
        ),
        MovingAverageCrossover(),
        RiskManager(limits),
        state_store,
        executor,
        arguments.symbol,
        arguments.timeframe,
        arguments.count,
        arguments.poll_seconds,
        logger,
        trading_filters,
        create_alerter(),
    )
    market_data = session.market_data
    try:
        market_data.connect()
        print(f"Paper session running for {arguments.symbol} {arguments.timeframe}; press Ctrl+C to stop.")
        session.run_forever(Event())
    except KeyboardInterrupt:
        print("Paper session stopped.")
    except MT5ConnectionError as error:
        raise SystemExit(str(error)) from error
    finally:
        market_data.disconnect()


def _add_cost_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--slippage", type=float, default=0.0, help="Adverse price movement per fill")
    parser.add_argument("--commission-per-unit", type=float, default=0.0, help="Round-trip commission per unit")


def _add_storage_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database", type=Path, default=Path("data/forexbot.db"))
    parser.add_argument("--no-save", action="store_true", help="Do not save this backtest result")


def _add_config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, help="Path to a TOML bot configuration file")


def _risk_limits_from_arguments(arguments) -> RiskLimits:
    if not arguments.config:
        return RiskLimits()
    settings = load_settings(arguments.config)
    if settings.mode == "live":
        raise SystemExit("Live mode is not implemented. Use backtest or demo mode.")
    return settings.risk_limits


def _run_backtest(candles, limits: RiskLimits, slippage: float, commission_per_unit: float):
    return Backtester(
        MovingAverageCrossover(),
        RiskManager(limits),
        limits.account_balance,
        slippage=slippage,
        commission_per_unit=commission_per_unit,
    ).run(candles)


def _print_result(result) -> None:
    print(f"Trades: {len(result.trades)}")
    print(f"Net profit: {result.net_profit:.2f}")
    print(f"Ending balance: {result.ending_balance:.2f}")
    print(f"Return: {result.return_percentage:.2%}")
    print(f"Win rate: {result.win_rate:.1%}")
    print(f"Profit factor: {result.profit_factor:.2f}")
    print(f"Maximum drawdown: {result.max_drawdown:.2f}")


def _save_result(arguments, result, source: str, symbol: str, timeframe: str, candle_count: int) -> None:
    if arguments.no_save:
        return
    run_id = BacktestStore(arguments.database).save_run(
        BacktestRun(source, symbol, timeframe, candle_count, result)
    )
    print(f"Saved run: {arguments.database} (id {run_id})")


if __name__ == "__main__":
    main()
