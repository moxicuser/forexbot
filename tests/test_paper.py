import json
from pathlib import Path

import pytest

from forexbot.audit import configure_audit_logger
from forexbot.domain import Side
from forexbot.paper import PaperExecutor, PaperOrder
from forexbot.storage import PaperStateStore


def test_paper_order_applies_adverse_slippage_and_prevents_duplicates(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    executor = PaperExecutor(slippage=0.0001, audit_logger=configure_audit_logger(log_path))
    order = PaperOrder("signal-1", "EURUSD", Side.BUY, 10_000, 1.1)

    filled = executor.submit(order)
    duplicate = executor.submit(order)

    assert filled.fill_price == pytest.approx(1.1001)
    assert not filled.duplicate
    assert duplicate.duplicate
    events = [json.loads(line)["event"] for line in log_path.read_text().splitlines()]
    assert events == ["paper_order_filled", "paper_order_duplicate"]


def test_paper_state_recovers_fills_after_restart(tmp_path: Path) -> None:
    store = PaperStateStore(tmp_path / "paper.db")
    order = PaperOrder("signal-2", "EURUSD", Side.SELL, 10_000, 1.1)
    PaperExecutor(save_fill=store.save_fill).submit(order)

    recovered_executor = PaperExecutor(existing_fills=store.load_fills())

    assert recovered_executor.submit(order).duplicate
