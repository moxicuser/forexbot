import pytest

from forexbot.domain import Side, Signal
from forexbot.risk import RiskLimits, RiskManager


def test_position_size_is_limited_by_risk() -> None:
    manager = RiskManager(RiskLimits(account_balance=10_000, risk_per_trade=0.01))
    signal = Signal(Side.BUY, stop_loss=1.095, take_profit=1.11, reason="test")

    assert manager.approve(signal, entry_price=1.1, open_trades=0, daily_loss=0) == pytest.approx(20_000)


def test_daily_loss_limit_blocks_trade() -> None:
    manager = RiskManager(RiskLimits(account_balance=10_000, max_daily_loss=0.03))
    signal = Signal(Side.BUY, stop_loss=1.095, take_profit=1.11, reason="test")

    assert manager.approve(signal, 1.1, open_trades=0, daily_loss=300) is None


def test_drawdown_limit_blocks_trade() -> None:
    manager = RiskManager(RiskLimits(account_balance=10_000, max_drawdown=0.1))
    signal = Signal(Side.BUY, stop_loss=1.095, take_profit=1.11, reason="test")

    assert manager.approve(signal, 1.1, open_trades=0, daily_loss=0, drawdown=0.1) is None


def test_depleted_balance_blocks_trade() -> None:
    manager = RiskManager(RiskLimits())
    signal = Signal(Side.BUY, stop_loss=1.095, take_profit=1.11, reason="test")

    assert manager.approve(signal, 1.1, open_trades=0, daily_loss=0, current_balance=0) is None


@pytest.mark.parametrize(
    ("side", "stop_loss", "take_profit"),
    [
        (Side.BUY, 1.105, 1.11),
        (Side.BUY, 1.095, 1.09),
        (Side.SELL, 1.095, 1.09),
        (Side.SELL, 1.105, 1.11),
    ],
)
def test_invalid_stop_or_target_geometry_blocks_trade(side, stop_loss, take_profit) -> None:
    manager = RiskManager(RiskLimits())
    signal = Signal(side, stop_loss, take_profit, "invalid geometry")

    assert manager.approve(signal, 1.1, open_trades=0, daily_loss=0) is None


def test_non_finite_risk_settings_are_rejected() -> None:
    with pytest.raises(ValueError):
        RiskManager(RiskLimits(account_balance=float("nan")))
