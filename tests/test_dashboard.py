import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from forexbot.dashboard import _run_uploaded_csv_backtest, create_app


def test_dashboard_has_branded_empty_state(tmp_path: Path) -> None:
    app = create_app(tmp_path / "missing.db")
    home = next(route.endpoint for route in app.routes if route.path == "/")

    page = home()

    assert "Research command center" in page
    assert "#080C12" in page
    assert "No saved backtests yet" not in page


def test_paper_api_reports_fresh_heartbeat_and_recent_error(tmp_path: Path) -> None:
    audit_path = tmp_path / "paper.jsonl"
    audit_path.write_text(
        "\n".join(
            json.dumps(event)
            for event in (
                {
                    "timestamp": (datetime.now(UTC) - timedelta(seconds=4)).isoformat(),
                    "event": "paper_session_error",
                    "data": {"error": "temporary failure"},
                },
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "event": "paper_session_heartbeat",
                    "data": {},
                },
            )
        ),
        encoding="utf-8",
    )
    app = create_app(tmp_path / "paper.db", audit_path)
    endpoint = next(route.endpoint for route in app.routes if route.path == "/api/paper")

    summary = endpoint()

    assert summary["session_state"] == "active"
    assert summary["session_active"] is True
    assert summary["last_session_error"] == {"error": "temporary failure"}


def test_paper_api_distinguishes_stale_from_missing_heartbeat(tmp_path: Path) -> None:
    audit_path = tmp_path / "paper.jsonl"
    audit_path.write_text(
        json.dumps(
            {
                "timestamp": (datetime.now(UTC) - timedelta(minutes=2)).isoformat(),
                "event": "paper_session_poll",
                "data": {},
            }
        ),
        encoding="utf-8",
    )
    app = create_app(tmp_path / "paper.db", audit_path)
    endpoint = next(route.endpoint for route in app.routes if route.path == "/api/paper")

    assert endpoint()["session_state"] == "stale"
    missing_app = create_app(tmp_path / "missing.db", tmp_path / "missing.jsonl")
    missing_endpoint = next(route.endpoint for route in missing_app.routes if route.path == "/api/paper")
    assert missing_endpoint()["session_state"] == "inactive"


def test_csv_workbench_runs_and_saves_backtest(tmp_path: Path) -> None:
    csv_contents = "timestamp,open,high,low,close\n" + "".join(
        f"{datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day):%Y-%m-%dT%H:%M:%S%z},1.1,1.101,1.099,1.1\n"
        for day in range(32)
    )

    result = _run_uploaded_csv_backtest(
        tmp_path / "research.db",
        {
            "csv": csv_contents,
            "symbol": "EURUSD",
            "timeframe": "M15",
            "slippage": "0.00005",
            "commission_per_unit": "0",
        },
    )

    assert result["run_id"] == 1
    assert result["candle_count"] == 32
    assert result["symbol"] == "EURUSD"


def test_csv_workbench_rejects_invalid_metadata(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Symbol"):
        _run_uploaded_csv_backtest(
            tmp_path / "research.db",
            {"csv": "timestamp,open,high,low,close\n", "symbol": "../x", "timeframe": "M15"},
        )
