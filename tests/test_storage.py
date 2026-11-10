from datetime import UTC, datetime, timedelta
from pathlib import Path

from forexbot.backtest import BacktestResult
from forexbot.domain import Candle, Side, Trade
from forexbot.paper import PaperFill
from forexbot.storage import BacktestRun, BacktestStore, PaperStateStore


def test_store_saves_backtest_run(tmp_path: Path) -> None:
    store = BacktestStore(tmp_path / "history.db")
    result = BacktestResult([Trade(Side.BUY, 1.0, 1.1, 100)], 10_000)

    run_id = store.save_run(BacktestRun("mt5", "EURUSD", "M15", 500, result))

    assert run_id == 1
    assert store.database_path.exists()
    assert store.recent_runs()[0]["symbol"] == "EURUSD"


def test_paper_dashboard_summary_calculates_validation_metrics(tmp_path: Path) -> None:
    store = PaperStateStore(tmp_path / "paper.db")
    store.save_fill(PaperFill("loss", "EURUSD", Side.BUY, 100, 1.1, False, 1.09, 1.12))
    store.save_fill(PaperFill("win", "GBPUSD", Side.BUY, 100, 1.1, False, 1.09, 1.12))
    timestamp = datetime.now(UTC)
    store.close_positions("EURUSD", Candle(timestamp, 1.1, 1.13, 1.08, 1.1))
    store.close_positions("GBPUSD", Candle(timestamp + timedelta(seconds=1), 1.1, 1.13, 1.1, 1.12))

    summary = store.dashboard_summary()

    assert summary["performance"] == {
        "closed_trade_count": 2,
        "winning_trades": 1,
        "losing_trades": 1,
        "win_rate": 0.5,
        "profit_factor": 2.0,
        "max_drawdown": 0.0001,
    }
    assert len(summary["recent_closed_trades"]) == 2
