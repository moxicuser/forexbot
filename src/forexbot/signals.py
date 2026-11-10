"""Read-only market analysis and rule-based setup generation."""

from collections.abc import Sequence
from datetime import UTC, datetime
from math import isfinite

from forexbot.domain import Candle


def analyze_market(
    candles: Sequence[Candle],
    quote: dict[str, float | str],
    symbol: str,
    timeframe: str,
    max_spread_points: float = 30.0,
) -> dict[str, object]:
    if len(candles) < 51:
        raise ValueError("At least 51 completed candles are required for analysis")
    if not isfinite(max_spread_points) or max_spread_points <= 0:
        raise ValueError("max_spread_points must be positive")

    closes = [candle.close for candle in candles]
    sma_fast = sum(closes[-20:]) / 20
    sma_slow = sum(closes[-50:]) / 50
    changes = [current - previous for previous, current in zip(closes[-15:-1], closes[-14:])]
    gains = sum(max(change, 0.0) for change in changes) / 14
    losses = sum(max(-change, 0.0) for change in changes) / 14
    rsi = 50.0 if gains == 0 and losses == 0 else 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)
    true_ranges = [
        max(
            candle.high - candle.low,
            abs(candle.high - previous.close),
            abs(candle.low - previous.close),
        )
        for previous, candle in zip(candles[-15:-1], candles[-14:])
    ]
    atr = sum(true_ranges) / len(true_ranges)
    last = candles[-1]
    spread_points = float(quote["spread_points"])
    if not isfinite(spread_points) or spread_points < 0:
        raise ValueError("MT5 returned an invalid spread")
    quote_time = datetime.fromisoformat(str(quote["timestamp"]))
    quote_age_seconds = max(0.0, (datetime.now(UTC) - quote_time.astimezone(UTC)).total_seconds())

    if sma_fast > sma_slow and last.close > sma_fast:
        trend = "bullish"
        candidate = "BUY"
        momentum_confirmed = 50 <= rsi <= 68
    elif sma_fast < sma_slow and last.close < sma_fast:
        trend = "bearish"
        candidate = "SELL"
        momentum_confirmed = 32 <= rsi <= 50
    else:
        trend = "mixed"
        candidate = "WAIT"
        momentum_confirmed = False

    if quote_age_seconds > 120:
        signal = "WAIT"
        reason = f"Latest MT5 quote is stale ({quote_age_seconds:.0f} seconds old)"
    elif candidate != "WAIT" and not momentum_confirmed:
        signal = "WAIT"
        reason = f"{trend.title()} trend, but RSI {rsi:.1f} does not confirm the setup"
    elif candidate != "WAIT" and spread_points > max_spread_points:
        signal = "WAIT"
        reason = f"Spread {spread_points:.1f} points exceeds the {max_spread_points:.1f}-point limit"
    elif candidate != "WAIT":
        signal = f"{candidate} SETUP"
        reason = f"{trend.title()} trend with RSI confirmation; levels use 1.5× ATR risk and 2R target"
    else:
        signal = "WAIT"
        reason = "Trend and price structure are not aligned"

    entry = float(quote["ask"] if candidate == "BUY" else quote["bid"]) if signal != "WAIT" else None
    stop_loss = entry - 1.5 * atr if candidate == "BUY" and entry is not None else (
        entry + 1.5 * atr if candidate == "SELL" and entry is not None else None
    )
    take_profit = entry + 3 * atr if candidate == "BUY" and entry is not None else (
        entry - 3 * atr if candidate == "SELL" and entry is not None else None
    )
    if quote_age_seconds > 120:
        watch_for = "Wait for a fresh MT5 quote before interpreting an entry."
    elif spread_points > max_spread_points:
        watch_for = f"Watch for spread to return to {max_spread_points:.1f} points or below."
    elif candidate != "WAIT" and not momentum_confirmed:
        momentum_range = "50–68" if candidate == "BUY" else "32–50"
        watch_for = f"Wait for RSI(14) to enter the {momentum_range} confirmation range."
    elif candidate == "WAIT":
        watch_for = "Wait for the completed-candle trend and price position to align."
    else:
        boundary = "above" if candidate == "BUY" else "below"
        watch_for = f"The setup depends on price holding {boundary} the 20-period average; reassess after each completed candle."
    explanation = (
        f"{trend.title()} bias from the 20/50-period averages; RSI(14) is {rsi:.1f}; "
        f"ATR(14) is {atr:.5f}; spread is {spread_points:.1f} points. {reason}."
    )

    return {
        "symbol": symbol,
        "timeframe": timeframe.upper(),
        "signal": signal,
        "reason": reason,
        "explanation": explanation,
        "watch_for": watch_for,
        "trend": trend,
        "rsi_14": rsi,
        "atr_14": atr,
        "sma_20": sma_fast,
        "sma_50": sma_slow,
        "last_completed_candle": last.timestamp.isoformat(),
        "quote_timestamp": quote["timestamp"],
        "quote_age_seconds": quote_age_seconds,
        "bid": quote["bid"],
        "ask": quote["ask"],
        "spread_points": spread_points,
        "spread_limit_points": max_spread_points,
        "entry_reference": entry,
        "stop_loss_reference": stop_loss,
        "take_profit_reference": take_profit,
        "candles": [
            {
                "time": candle.timestamp.isoformat(),
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
            }
            for candle in candles[-80:]
        ],
        "execution": "read-only analysis; no order placed",
    }
