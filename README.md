# ForexBot

A local-first forex analysis and paper-testing tool. Its main purpose is to turn current MT5 market data into timestamped, explainable rule-based setups and useful historical analytics. MT5 access is read-only: the app does not place broker orders, and no signal can guarantee an ideal entry or profit.

## Current capabilities

- CSV candle ingestion (`timestamp,open,high,low,close`)
- Moving-average crossover example strategy
- Risk approval before every simulated order
- Backtest metrics: return, win rate, profit factor, and drawdown
- Unit tests for risk rules and the backtester
- Local Signal Desk using completed MT5 candles and current bid/ask quotes
- Trend, RSI, ATR, spread gating, quote freshness, and reference risk levels

## Quick start

Requires Python 3.11+.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[mt5,dev]"
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m forexbot.cli backtest path\to\candles.csv
```

With MT5 open and logged into a demo account, verify the local connection:

```powershell
.\.venv\Scripts\python -m forexbot.cli mt5-status --terminal-path "C:\Program Files\MetaTrader 5\terminal64.exe"
```

The MT5 adapter currently reads market data only. It cannot place, modify, or close trades.

Run the example strategy against recent MT5 candles without placing orders:

```powershell
.\.venv\Scripts\python -m forexbot.cli mt5-backtest EURUSD --timeframe M15 --count 2000
```

Each backtest is saved to `data/forexbot.db` by default. Add `--no-save` for a one-off result.

Copy `config.example.toml` to `config.toml` to keep risk settings outside the code, then pass it to a backtest with `--config config.toml`. Live mode is intentionally unavailable.

The `[filters]` section controls paper entries. `max_spread_points` blocks entries when the current MT5 bid/ask spread exceeds the limit. `start_hour_utc` and `end_hour_utc` restrict entries to a UTC hour window; `0` to `24` allows all hours. Open positions still receive stop-loss/take-profit processing outside that window. The `[mt5]` `server_utc_offset_hours` setting defaults to `"auto"`; auto mode infers an integer-hour shift from a fresh tick and rejects ambiguous timestamps. Set an explicit numeric offset in hours if your broker uses a fractional-hour offset or the market is closed while the adapter starts.

## Paper execution and audit logs

`forexbot.paper` simulates demo-only order fills with configurable adverse slippage and duplicate-order protection. It has no broker integration. Use `forexbot.audit` to write structured JSON audit events to a local file such as `logs/audit.jsonl`.

`PaperStateStore` persists simulated fills to SQLite so an application restart can reload them before accepting new paper orders.

Run the signal-driven paper session against completed MT5 candles:

```powershell
.\.venv\Scripts\python -m forexbot.cli paper-session EURUSD --timeframe M15 --config config.example.toml
```

The session polls completed candles, validates price data, applies spread and UTC-hour filters to entries, records heartbeat and risk events in `logs/paper-session.jsonl`, retries the terminal connection after errors, and stops with Ctrl+C. Simulated positions close when a stop-loss or take-profit is reached. If both levels fall within one candle, it assumes the stop-loss filled first. Realized profit, daily loss, maximum drawdown, open positions, and processed-candle cursors persist in SQLite for recovery after restart. Use `--slippage 0.00005` to model adverse fills.

Telegram alerts are optional. Set `FOREXBOT_TELEGRAM_BOT_TOKEN` and `FOREXBOT_TELEGRAM_CHAT_ID` in the process environment before starting the session. The bot sends paper entry/exit, risk-filter, and session-error notices. Credentials are not stored in project config or the database.

Run the heartbeat watchdog in a second terminal so it can detect when the paper-session process stops:

```powershell
.\.venv\Scripts\python -m forexbot.watchdog --stale-after 45 --check-interval 10
```

The watchdog alerts once when the session becomes unresponsive and once when it recovers. It uses the same optional Telegram environment variables and writes no credentials to logs.

## Local dashboard

Start the local monitoring page with:

```powershell
.\.venv\Scripts\python -m forexbot.dashboard
```

Pass `--config config.example.toml` to use the configured spread limit for signal gating.

Open `http://127.0.0.1:8000` in your browser. The dashboard shows MT5 status, saved backtests, paper-session heartbeat, and simulated open positions; it has no broker-login or order-execution controls.

The Signal Desk requests current quotes and completed candles from the logged-in local MT5 terminal and displays a BUY SETUP, SELL SETUP, or WAIT with a candlestick chart, trend, RSI, ATR-based reference levels, spread, and source timestamps. Its local analyst explains the rule result and what condition to watch next; this first version uses explicit deterministic rules, not a generative AI model. It refuses to suggest a setup when the quote is stale, the spread exceeds the configured limit (30 points by default), or trend/momentum conditions disagree. These are transparent technical rules, not certainty or personalized financial advice.

The dashboard also reports paper-validation statistics (closed-trade count, win rate, profit factor, and realized drawdown against a $10,000 baseline) and the recent simulated trade ledger. These are historical simulations, not live account results.

The strategy is intentionally an example, not financial advice or evidence of profitability. Use `--slippage` and `--commission-per-unit` to model broker costs; validate results through realistic backtests and extended demo trading before considering live use.

## Next milestones

1. **Live market intelligence — in progress:** local read-only MT5 feed, freshness/spread checks, and explainable trend/momentum/volatility setups. Next: configurable rules, multiple symbol/timeframe watchlists, signal history/alerts, and evaluate an optional AI explainer with explicit privacy and API-cost controls.
2. **Realistic research analytics — in progress:** saved CSV/MT5 backtests and paper trade performance. Next: remove strategy assumptions from the UI, add out-of-sample and walk-forward analysis, and show costs and equity curves.
3. **Paper validation — ongoing:** run the signal rules against historical data and an extended simulated/demo period; compare signals, spreads, slippage, drawdown, and outcomes before tuning.
4. **Execution review — future and gated:** only after measured validation, separately review any broker execution design. The current tool remains read-only and paper-only; no live-order API is included.
