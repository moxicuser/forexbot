"""Local-only monitoring dashboard for ForexBot."""

import argparse
from html import escape
import json
from math import isfinite
from pathlib import Path
import re
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from forexbot.backtest import Backtester
from forexbot.config import load_settings
from forexbot.data import parse_candles_csv
from forexbot.mt5 import MT5ConnectionError, MT5MarketData
from forexbot.risk import RiskLimits, RiskManager
from forexbot.storage import BacktestRun, BacktestStore, PaperStateStore
from forexbot.strategy import MovingAverageCrossover
from forexbot.signals import analyze_market


def create_app(
    database_path: Path = Path("data/forexbot.db"),
    audit_path: Path = Path("logs/paper-session.jsonl"),
    max_spread_points: float = 30.0,
) -> FastAPI:
    app = FastAPI(title="ForexBot Dashboard", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        runs = BacktestStore(database_path).recent_runs()
        total_profit = sum(float(run["net_profit"]) for run in runs)
        profitable_runs = sum(float(run["net_profit"]) > 0 for run in runs)
        latest_run = runs[0] if runs else None
        rows = "".join(
            f"<tr><td><span class='symbol'>{escape(str(run['symbol']))}</span><span class='subtle'>{escape(str(run['source']))} · {escape(str(run['timeframe']))}</span></td>"
            f"<td>{run['trade_count']}</td>"
            f"<td class='{'positive' if float(run['net_profit']) >= 0 else 'negative'}'>{float(run['net_profit']):+,.2f}</td>"
            f"<td>{float(run['max_drawdown']):,.2f}</td>"
            f"<td class='subtle'>{escape(str(run['created_at']))[:19].replace('T', ' ')}</td>"
            "</tr>"
            for run in runs
        ) or "<tr><td colspan='5' class='empty'>Run an MT5 or CSV backtest to populate this space.</td></tr>"
        last_symbol = escape(str(latest_run["symbol"])) if latest_run else "—"
        last_timeframe = escape(str(latest_run["timeframe"])) if latest_run else "No runs yet"
        return f"""
        <!doctype html>
        <html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>ForexBot Command Center</title>
        <style>
        :root{{--canvas:#080C12;--surface:#101722;--surface-raised:#172130;--ink:#F8FAFC;--muted:#94A3B8;--blue:#3B82F6;--blue-light:#60A5FA;--line:#273548;--slate:#CBD5E1}}
        *{{box-sizing:border-box}} body{{margin:0;min-width:320px;background:radial-gradient(circle at 12% 0%,#162C4D 0,transparent 30rem),var(--canvas);color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}}
        input,select,button{{font:inherit}} .workbench{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;padding:22px 24px}} .field{{display:grid;gap:7px;color:var(--muted);font-size:.8rem;font-weight:650}} .field input,.field select{{width:100%;padding:11px 12px;border:1px solid var(--line);border-radius:9px;background:#080C12;color:var(--ink)}} .field input[type=file]{{padding:8px}} .action{{grid-column:1/-1;display:flex;align-items:center;gap:14px;flex-wrap:wrap}} .button{{border:0;border-radius:9px;background:var(--blue);color:white;padding:12px 18px;font-weight:750;cursor:pointer}} .button:disabled{{opacity:.55;cursor:wait}} .result{{color:var(--muted);font-size:.86rem;line-height:1.6}} .result.success{{color:var(--blue-light)}} .result.error{{color:var(--slate)}}
        .signal-layout{{display:grid;grid-template-columns:1.2fr 1fr;gap:20px;padding:22px 24px}} .signal-state{{font-size:clamp(2rem,5vw,3.5rem);font-weight:800;letter-spacing:-.06em;margin:4px 0 8px}} .signal-reason{{color:var(--muted);line-height:1.6;max-width:560px}} .signal-meta{{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin-top:18px}} .signal-meta span{{padding:7px 10px;border:1px solid var(--line);border-radius:999px;background:#080C12;color:var(--muted);font-size:.78rem}} .signal-metrics{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}} .signal-metric{{background:#080C12;border:1px solid var(--line);border-radius:10px;padding:13px}} .signal-metric label{{display:block;color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.06em}} .signal-metric strong{{display:block;margin-top:7px;font-size:1.05rem}} .desk-controls{{display:flex;gap:10px;align-items:center}} .desk-controls select,.desk-controls input{{padding:9px 11px;border:1px solid var(--line);border-radius:8px;background:#080C12;color:var(--ink)}} .desk-controls input{{width:110px}} .desk-controls button{{padding:9px 13px}}
        .chart-wrap{{padding:0 24px 22px}} .chart-wrap canvas{{display:block;width:100%;height:260px;border:1px solid var(--line);border-radius:10px;background:#080C12}} .chart-caption{{color:var(--muted);font-size:.75rem;margin:0 0 9px}}
        .analyst-note{{margin:0 24px 22px;padding:18px 20px;border:1px solid var(--line);border-radius:12px;background:#101722}} .analyst-note h3{{margin:0 0 8px;font-size:.9rem}} .analyst-note p{{margin:0;color:var(--muted);line-height:1.6;font-size:.86rem}} .analyst-note .watch{{margin-top:10px;color:var(--slate)}}
        .shell{{max-width:1180px;margin:auto;padding:32px 24px 56px}} .topbar{{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:42px}} .brand{{display:flex;align-items:center;gap:12px;font-weight:750;letter-spacing:-.04em;font-size:1.15rem}} .mark{{width:34px;height:34px;display:grid;place-items:center;background:linear-gradient(135deg,#2563EB,var(--blue-light));border-radius:10px;box-shadow:0 12px 32px #0008}} .mark svg{{width:20px;height:20px}} .eyebrow{{color:var(--blue-light);font-size:.72rem;font-weight:800;letter-spacing:.13em;text-transform:uppercase;margin:0 0 8px}}
        .status{{display:flex;align-items:center;gap:9px;padding:9px 13px;border:1px solid var(--line);border-radius:999px;background:#0C121B;font-size:.84rem;color:var(--muted)}} .dot{{width:8px;height:8px;border-radius:50%;background:#64748B;box-shadow:0 0 0 4px #64748b1c}} .status.live .dot{{background:var(--blue-light);box-shadow:0 0 0 4px #60a5fa1c}} .status.live{{color:var(--blue-light)}}
        h1{{font-size:clamp(2.2rem,5vw,4.4rem);letter-spacing:-.065em;line-height:.95;max-width:700px;margin:0 0 18px}} .intro{{color:var(--muted);max-width:590px;line-height:1.6;margin:0}} .hero{{margin-bottom:34px}} .grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:24px}} .card{{background:linear-gradient(145deg,#152031,#0F1620);border:1px solid var(--line);border-radius:14px;padding:20px;min-height:128px;box-shadow:0 18px 40px #00000042}} .card-label{{color:var(--muted);font-size:.78rem;font-weight:700;letter-spacing:.05em;text-transform:uppercase}} .metric{{font-size:1.75rem;font-weight:750;letter-spacing:-.05em;margin:18px 0 3px}} .metric.positive{{color:var(--blue-light)}} .metric.negative{{color:var(--slate)}} .metric.note{{font-size:1.2rem;color:var(--blue-light)}} .subtle{{display:block;color:var(--muted);font-size:.78rem;margin-top:4px}}
        .panel{{background:#0E151Fcc;border:1px solid var(--line);border-radius:16px;overflow:hidden;box-shadow:0 18px 48px #00000042}} .panel-header{{padding:22px 24px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;gap:12px}} h2{{font-size:1.05rem;letter-spacing:-.025em;margin:0}} .badge{{color:var(--blue-light);font-size:.75rem;font-weight:750;background:#3b82f614;padding:7px 10px;border-radius:999px}}
        table{{width:100%;border-collapse:collapse}} th{{color:var(--muted);font-size:.7rem;letter-spacing:.08em;text-transform:uppercase;font-weight:700;text-align:left;padding:14px 24px}} td{{padding:17px 24px;border-top:1px solid #1F2C3C;font-size:.9rem}} tr:hover td{{background:#ffffff04}} .symbol{{font-weight:750;letter-spacing:-.02em}} .positive{{color:var(--blue-light)}} .negative{{color:var(--slate)}} .empty{{text-align:center;color:var(--muted);padding:42px}} .footnote{{color:var(--muted);font-size:.78rem;line-height:1.55;margin:20px 0 0}}
        @media(max-width:760px){{.shell{{padding:22px 16px 38px}}.topbar{{margin-bottom:30px}}.grid{{grid-template-columns:repeat(2,1fr)}}.card{{min-height:112px;padding:16px}}th:nth-child(4),td:nth-child(4),th:nth-child(5),td:nth-child(5){{display:none}}td,th{{padding-left:16px;padding-right:16px}}}}
        @media(max-width:520px){{.workbench{{grid-template-columns:1fr;padding:16px}}.action{{grid-column:auto}}}}
        @media(max-width:700px){{.signal-layout{{grid-template-columns:1fr;padding:18px}}.desk-controls{{flex-wrap:wrap}}}}
        </style></head><body><main class='shell'><nav class='topbar'><div class='brand'><span class='mark'><svg viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='2.4'><path d='M5 17 10 12l3 3 6-7'/><path d='M15 8h4v4'/></svg></span>forexbot</div><div id='status' class='status'><span class='dot'></span><span>Checking MT5</span></div></nav>
        <section class='hero'><p class='eyebrow'>Research command center</p><h1>Trade ideas.<br><span style='color:var(--blue-light)'>Measured calmly.</span></h1><p class='intro'>A local, read-only view of your strategy research. Backtests are simulations—not signals to trade—and this dashboard never stores broker credentials.</p></section>
        <section class='panel' style='margin-bottom:22px'><div class='panel-header'><div><h2>Live signal desk</h2><span class='subtle'>Read-only analysis from completed MT5 candles and the current terminal quote</span></div><div class='desk-controls'><input id='analysis-symbol' value='EURUSD' maxlength='20' aria-label='Market symbol'><select id='analysis-timeframe' aria-label='Timeframe'><option>M15</option><option>M5</option><option>M1</option><option>M30</option><option>H1</option><option>H4</option><option>D1</option></select><button class='button' id='analysis-refresh' type='button'>Refresh</button></div></div><div class='signal-layout'><div><div id='analysis-signal' class='signal-state'>CONNECTING</div><div id='analysis-reason' class='signal-reason'>Connecting to the local MT5 terminal and loading recent market data…</div><div class='signal-meta'><span id='analysis-market'>EURUSD · M15</span><span id='analysis-updated'>Waiting for quote</span></div></div><div class='signal-metrics'><div class='signal-metric'><label>Market bias</label><strong id='analysis-trend'>—</strong></div><div class='signal-metric'><label>RSI · 14</label><strong id='analysis-rsi'>—</strong></div><div class='signal-metric'><label>Bid / Ask</label><strong id='analysis-quote'>—</strong></div><div class='signal-metric'><label>Spread</label><strong id='analysis-spread'>—</strong></div><div class='signal-metric'><label>Entry reference</label><strong id='analysis-entry'>—</strong></div><div class='signal-metric'><label>ATR stop / target</label><strong id='analysis-levels'>—</strong></div></div></div><div class='chart-wrap'><p class='chart-caption'>Recent completed candles · green = up, red = down · dashed = 20-bar average</p><canvas id='market-chart' aria-label='Recent MT5 price candles'></canvas></div><aside class='analyst-note'><h3>Market analyst · transparent rules</h3><p id='analysis-explanation'>Waiting for market analysis.</p><p id='analysis-watch' class='watch'>What to watch: waiting for data.</p></aside></section>
        <section class='grid'><article class='card'><div class='card-label'>Saved runs</div><div class='metric'>{len(runs)}</div><span class='subtle'>Research snapshots</span></article><article class='card'><div class='card-label'>Sum of run P/L</div><div class='metric {'positive' if total_profit >= 0 else 'negative'}'>{total_profit:+,.2f}</div><span class='subtle'>Separate runs; not a portfolio result</span></article><article class='card'><div class='card-label'>Profitable runs</div><div class='metric'>{profitable_runs}/{len(runs)}</div><span class='subtle'>Historical simulations</span></article><article class='card'><div class='card-label'>Latest market</div><div class='metric note'>{last_symbol}</div><span class='subtle'>{last_timeframe}</span></article></section>
        <section class='grid'><article class='card'><div class='card-label'>Paper realized P/L</div><div id='paper-profit' class='metric'>—</div><span class='subtle'>Closed simulated positions</span></article><article class='card'><div class='card-label'>Open paper positions</div><div id='paper-open-count' class='metric'>—</div><span class='subtle'>Persisted in local state</span></article><article class='card'><div class='card-label'>Paper session</div><div id='paper-session-state' class='metric note'>Checking</div><span id='paper-heartbeat' class='subtle'>Waiting for heartbeat</span></article><article class='card'><div class='card-label'>Execution mode</div><div class='metric note'>Paper</div><span class='subtle'>Simulated fills only</span></article></section>
        <section class='panel' style='margin-bottom:22px'><div class='panel-header'><h2>Open paper positions</h2><span class='badge'>SIMULATED</span></div><table><thead><tr><th>Market</th><th>Side</th><th>Units</th><th>Entry</th><th>Stop loss</th><th>Take profit</th></tr></thead><tbody id='paper-positions'><tr><td colspan='6' class='empty'>Loading paper state...</td></tr></tbody></table></section>
        <section class='panel' style='margin-bottom:22px'><div class='panel-header'><h2>Paper validation</h2><span class='badge'>CLOSED TRADES · $10K BASELINE</span></div><div class='grid' style='padding:18px 20px;margin:0'><article class='card'><div class='card-label'>Closed trades</div><div id='paper-trade-count' class='metric'>—</div></article><article class='card'><div class='card-label'>Win rate</div><div id='paper-win-rate' class='metric'>—</div></article><article class='card'><div class='card-label'>Profit factor</div><div id='paper-profit-factor' class='metric'>—</div></article><article class='card'><div class='card-label'>Max realized drawdown</div><div id='paper-drawdown' class='metric'>—</div></article></div><table><thead><tr><th>Market</th><th>Side</th><th>Units</th><th>Entry</th><th>Exit</th><th>Net P/L</th><th>Closed</th></tr></thead><tbody id='paper-closed-trades'><tr><td colspan='7' class='empty'>No closed paper trades yet.</td></tr></tbody></table></section>
        <section class='panel' style='margin-bottom:22px'><div class='panel-header'><h2>CSV strategy workbench</h2><span class='badge'>SIMULATED · NO ORDERS</span></div><form id='backtest-form' class='workbench'><label class='field'>Market symbol<input name='symbol' value='EURUSD' maxlength='20' required></label><label class='field'>Timeframe<select name='timeframe'><option>M15</option><option>M5</option><option>M1</option><option>M30</option><option>H1</option><option>H4</option><option>D1</option></select></label><label class='field'>Adverse slippage per fill<input name='slippage' type='number' min='0' step='0.00001' value='0.00005'></label><label class='field'>Commission per unit<input name='commission' type='number' min='0' step='0.00001' value='0'></label><label class='field' style='grid-column:1/-1'>OHLC CSV file<input name='file' type='file' accept='.csv,text/csv' required></label><div class='action'><button id='backtest-submit' class='button' type='submit'>Run backtest</button><span id='backtest-result' class='result' aria-live='polite'>CSV is processed in memory and not saved as an uploaded file.</span></div></form></section>
        <section class='panel'><div class='panel-header'><h2>Recent research runs</h2><span class='badge'>LOCAL ONLY</span></div><table><thead><tr><th>Market</th><th>Trades</th><th>Net P/L</th><th>Drawdown</th><th>Recorded</th></tr></thead><tbody>{rows}</tbody></table></section><p class='footnote'>Backtests and paper positions are simulations. Review spread, slippage, commission, and out-of-sample results before making any trading decision.</p></main>
        <script>
        fetch('/api/status').then(r=>r.json()).then(x=>{{const e=document.getElementById('status');e.classList.toggle('live',x.mt5_connected);e.children[1].textContent=x.mt5_connected?'MT5 terminal connected':'MT5 unavailable'}}).catch(()=>document.getElementById('status').children[1].textContent='MT5 unavailable');
        function drawMarketChart(candles,average){{const canvas=document.getElementById('market-chart');const bounds=canvas.getBoundingClientRect();if(!bounds.width||!candles.length)return;const ratio=window.devicePixelRatio||1;canvas.width=bounds.width*ratio;canvas.height=260*ratio;const ctx=canvas.getContext('2d');ctx.scale(ratio,ratio);const width=bounds.width,height=260,left=58,right=12,top=14,bottom=25,plotWidth=width-left-right,plotHeight=height-top-bottom;const highest=Math.max(...candles.map(candle=>candle.high));const lowest=Math.min(...candles.map(candle=>candle.low));const padding=(highest-lowest)*0.08||0.0001;const max=highest+padding,min=lowest-padding;const y=price=>top+(max-price)/(max-min)*plotHeight;ctx.font='11px ui-sans-serif,system-ui';ctx.textBaseline='middle';for(let index=0;index<=4;index++){{const price=max-(max-min)*index/4;const yPos=top+plotHeight*index/4;ctx.strokeStyle='#273548';ctx.beginPath();ctx.moveTo(left,yPos);ctx.lineTo(width-right,yPos);ctx.stroke();ctx.fillStyle='#94A3B8';ctx.textAlign='right';ctx.fillText(price.toFixed(5),left-8,yPos)}}const step=plotWidth/candles.length;for(let index=0;index<candles.length;index++){{const candle=candles[index];const center=left+step*(index+0.5);const rising=candle.close>=candle.open;const color=rising?'#3B8F6B':'#C65D63';ctx.strokeStyle=color;ctx.fillStyle=color;ctx.beginPath();ctx.moveTo(center,y(candle.high));ctx.lineTo(center,y(candle.low));ctx.stroke();const bodyTop=y(Math.max(candle.open,candle.close));const bodyHeight=Math.max(1,Math.abs(y(candle.open)-y(candle.close)));ctx.fillRect(center-Math.max(1,step*0.28),bodyTop,Math.max(2,step*0.56),bodyHeight)}}ctx.strokeStyle='#F8FAFC';ctx.setLineDash([5,4]);ctx.beginPath();ctx.moveTo(left,y(average));ctx.lineTo(width-right,y(average));ctx.stroke();ctx.setLineDash([])}}
        let analysisPending=false;async function refreshAnalysis(){{if(analysisPending)return;analysisPending=true;const symbol=document.getElementById('analysis-symbol').value.trim().toUpperCase();const timeframe=document.getElementById('analysis-timeframe').value;const state=document.getElementById('analysis-signal');state.textContent='LOADING';try{{const response=await fetch('/api/analysis?symbol='+encodeURIComponent(symbol)+'&timeframe='+encodeURIComponent(timeframe));const data=await response.json();if(!response.ok)throw new Error(data.detail||'Market analysis unavailable');state.textContent=data.signal;document.getElementById('analysis-reason').textContent=data.reason;document.getElementById('analysis-explanation').textContent=data.explanation;document.getElementById('analysis-watch').textContent='What to watch: '+data.watch_for;document.getElementById('analysis-market').textContent=data.symbol+' · '+data.timeframe;document.getElementById('analysis-updated').textContent='Bar '+new Date(data.last_completed_candle).toLocaleString()+' · quote '+Math.round(data.quote_age_seconds)+'s old';document.getElementById('analysis-trend').textContent=data.trend.toUpperCase();document.getElementById('analysis-rsi').textContent=Number(data.rsi_14).toFixed(1);document.getElementById('analysis-quote').textContent=Number(data.bid).toFixed(5)+' / '+Number(data.ask).toFixed(5);document.getElementById('analysis-spread').textContent=Number(data.spread_points).toFixed(1)+' pts';document.getElementById('analysis-entry').textContent=data.entry_reference===null?'—':Number(data.entry_reference).toFixed(5);document.getElementById('analysis-levels').textContent=data.stop_loss_reference===null?'—':Number(data.stop_loss_reference).toFixed(5)+' / '+Number(data.take_profit_reference).toFixed(5);drawMarketChart(data.candles,data.sma_20)}}catch(error){{state.textContent='UNAVAILABLE';document.getElementById('analysis-reason').textContent=error.message;document.getElementById('analysis-updated').textContent='';document.getElementById('analysis-explanation').textContent='Analysis is unavailable until live market data is restored.';document.getElementById('analysis-watch').textContent=''}}finally{{analysisPending=false}}}}document.getElementById('analysis-refresh').addEventListener('click',refreshAnalysis);refreshAnalysis();setInterval(refreshAnalysis,30000);
        document.getElementById('backtest-form').addEventListener('submit',async event=>{{event.preventDefault();const form=event.currentTarget;const button=document.getElementById('backtest-submit');const output=document.getElementById('backtest-result');const file=form.elements.file.files[0];if(!file)return;button.disabled=true;output.className='result';output.textContent='Running simulation…';try{{const csv=await file.text();const response=await fetch('/api/backtests/csv',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{csv,symbol:form.elements.symbol.value,timeframe:form.elements.timeframe.value,slippage:form.elements.slippage.value,commission_per_unit:form.elements.commission.value}})}});const result=await response.json();if(!response.ok)throw new Error(result.detail||'Backtest failed');output.className='result success';output.textContent='Saved run #'+result.run_id+' · '+result.trade_count+' trades · P/L '+Number(result.net_profit).toFixed(2)+' · Win rate '+(Number(result.win_rate)*100).toFixed(1)+'% · Max drawdown '+Number(result.max_drawdown).toFixed(2);window.location.reload()}}catch(error){{output.className='result error';output.textContent=error.message}}finally{{button.disabled=false}}}});
        fetch('/api/paper').then(r=>r.json()).then(x=>{{const profit=document.getElementById('paper-profit');profit.textContent=Number(x.realized_profit).toFixed(2);profit.classList.toggle('positive',x.realized_profit>=0);profit.classList.toggle('negative',x.realized_profit<0);document.getElementById('paper-open-count').textContent=x.open_positions.length;document.getElementById('paper-session-state').textContent=x.session_state.toUpperCase();document.getElementById('paper-heartbeat').textContent=x.heartbeat_age_seconds===null?'No heartbeat recorded':('Heartbeat '+x.heartbeat_age_seconds+'s ago'+(x.last_session_error?' · Recent session error':''));const perf=x.performance;document.getElementById('paper-trade-count').textContent=perf.closed_trade_count;document.getElementById('paper-win-rate').textContent=(Number(perf.win_rate)*100).toFixed(1)+'%';document.getElementById('paper-profit-factor').textContent=perf.profit_factor===null?'—':Number(perf.profit_factor).toFixed(2);document.getElementById('paper-drawdown').textContent=(Number(perf.max_drawdown)*100).toFixed(2)+'%';const body=document.getElementById('paper-positions');body.replaceChildren();if(!x.open_positions.length){{const row=document.createElement('tr');const cell=document.createElement('td');cell.colSpan=6;cell.className='empty';cell.textContent='No open paper positions.';row.append(cell);body.append(row)}}for(const p of x.open_positions){{const row=document.createElement('tr');for(const value of [p.symbol,p.side.toUpperCase(),Number(p.units).toLocaleString(),Number(p.fill_price).toFixed(5),p.stop_loss===null?'—':Number(p.stop_loss).toFixed(5),p.take_profit===null?'—':Number(p.take_profit).toFixed(5)]){{const cell=document.createElement('td');cell.textContent=value;row.append(cell)}}body.append(row)}}const closed=document.getElementById('paper-closed-trades');closed.replaceChildren();if(!x.recent_closed_trades.length){{const row=document.createElement('tr');const cell=document.createElement('td');cell.colSpan=7;cell.className='empty';cell.textContent='No closed paper trades yet.';row.append(cell);closed.append(row)}}for(const trade of x.recent_closed_trades){{const row=document.createElement('tr');for(const value of [trade.symbol,trade.side.toUpperCase(),Number(trade.units).toLocaleString(),Number(trade.fill_price).toFixed(5),Number(trade.exit_price).toFixed(5),Number(trade.profit_loss).toFixed(2),String(trade.closed_at).slice(0,19).replace('T',' ')]){{const cell=document.createElement('td');cell.textContent=value;row.append(cell)}}closed.append(row)}}}}).catch(()=>document.getElementById('paper-session-state').textContent='Unavailable');
        </script>
        </body></html>
        """

    @app.get("/api/status")
    def status() -> dict[str, bool]:
        market_data = MT5MarketData()
        try:
            market_data.connect()
            return {"mt5_connected": True}
        except MT5ConnectionError:
            return {"mt5_connected": False}
        finally:
            try:
                market_data.disconnect()
            except MT5ConnectionError:
                pass

    @app.get("/api/backtests")
    def backtests() -> list[dict[str, object]]:
        return BacktestStore(database_path).recent_runs()

    @app.post("/api/backtests/csv")
    async def run_csv_backtest(request: Request) -> dict[str, object]:
        body = await request.body()
        if len(body) > 2_000_000:
            raise HTTPException(status_code=413, detail="CSV upload must be smaller than 2 MB")
        try:
            payload = json.loads(body)
            return _run_uploaded_csv_backtest(database_path, payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="Request must be valid JSON") from None
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/analysis")
    def market_analysis(symbol: str = "EURUSD", timeframe: str = "M15") -> dict[str, object]:
        symbol = symbol.strip().upper()
        timeframe = timeframe.strip().upper()
        if not re.fullmatch(r"[A-Z0-9._-]{1,20}", symbol):
            raise HTTPException(status_code=400, detail="Invalid market symbol")
        if timeframe not in {"M1", "M5", "M15", "M30", "H1", "H4", "D1"}:
            raise HTTPException(status_code=400, detail="Unsupported timeframe")
        market_data = MT5MarketData()
        try:
            market_data.connect()
            candles = market_data.fetch_candles(symbol, timeframe, 120)
            quote = market_data.fetch_quote(symbol)
            return analyze_market(candles, quote, symbol, timeframe, max_spread_points)
        except MT5ConnectionError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        finally:
            try:
                market_data.disconnect()
            except MT5ConnectionError:
                pass

    @app.get("/api/paper")
    def paper_status() -> dict[str, object]:
        summary = PaperStateStore(database_path).dashboard_summary()
        events = _recent_audit_events(audit_path)
        latest = events[-1] if events else None
        heartbeat = next(
            (event for event in reversed(events) if event.get("event") in {"paper_session_poll", "paper_session_heartbeat"}),
            None,
        )
        heartbeat_at = heartbeat.get("timestamp") if heartbeat else None
        heartbeat_age = None
        if heartbeat_at:
            try:
                heartbeat_age = (datetime.now(UTC) - datetime.fromisoformat(str(heartbeat_at))).total_seconds()
            except ValueError:
                heartbeat_age = None
        recent_error = next(
            (event for event in reversed(events) if event.get("event") in {"paper_session_error", "paper_session_reconnect_failed"}),
            None,
        )
        summary["last_heartbeat"] = heartbeat_at
        summary["heartbeat_age_seconds"] = max(0, int(heartbeat_age)) if heartbeat_age is not None and heartbeat_age >= 0 else None
        summary["session_active"] = bool(heartbeat_age is not None and 0 <= heartbeat_age <= 30)
        summary["session_state"] = (
            "active" if summary["session_active"]
            else "stale" if heartbeat_age is not None and heartbeat_age > 30
            else "inactive"
        )
        summary["last_session_error"] = recent_error.get("data", {}) if recent_error else None
        summary["last_audit_event"] = latest.get("event") if latest else None
        return summary

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local ForexBot dashboard")
    parser.add_argument("--database", type=Path, default=Path("data/forexbot.db"))
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--audit-log", type=Path, default=Path("logs/paper-session.jsonl"))
    parser.add_argument("--config", type=Path, help="TOML settings; uses filters.max_spread_points")
    arguments = parser.parse_args()
    import uvicorn

    settings = load_settings(arguments.config) if arguments.config else None
    spread_limit = settings.trading_filters.max_spread_points if settings else 30.0
    uvicorn.run(
        create_app(arguments.database, arguments.audit_log, spread_limit),
        host="127.0.0.1",
        port=arguments.port,
    )


def _recent_audit_events(audit_path: Path) -> list[dict[str, object]]:
    if not audit_path.exists():
        return []
    with audit_path.open("rb") as log_file:
        log_file.seek(0, 2)
        end = log_file.tell()
        log_file.seek(max(0, end - 8192))
        lines = log_file.read().decode("utf-8", errors="replace").splitlines()
    events = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _run_uploaded_csv_backtest(database_path: Path, payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("Request body must be an object")
    csv_contents = payload.get("csv")
    symbol = str(payload.get("symbol", "")).strip().upper()
    timeframe = str(payload.get("timeframe", "")).strip().upper()
    if not isinstance(csv_contents, str) or not csv_contents.strip():
        raise ValueError("Choose a non-empty CSV file")
    if not re.fullmatch(r"[A-Z0-9._-]{1,20}", symbol):
        raise ValueError("Symbol may contain only letters, numbers, dots, underscores, and hyphens")
    if timeframe not in {"M1", "M5", "M15", "M30", "H1", "H4", "D1"}:
        raise ValueError("Choose a supported timeframe")
    try:
        slippage = float(payload.get("slippage", 0))
        commission = float(payload.get("commission_per_unit", 0))
    except (TypeError, ValueError) as error:
        raise ValueError("Slippage and commission must be numbers") from error
    if not isfinite(slippage) or not isfinite(commission) or slippage < 0 or commission < 0:
        raise ValueError("Slippage and commission must be finite and non-negative")
    candles = parse_candles_csv(csv_contents)
    result = Backtester(
        MovingAverageCrossover(),
        RiskManager(RiskLimits()),
        10_000,
        slippage=slippage,
        commission_per_unit=commission,
    ).run(candles)
    run_id = BacktestStore(database_path).save_run(
        BacktestRun("csv-upload", symbol, timeframe, len(candles), result)
    )
    return {
        "run_id": run_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "candle_count": len(candles),
        "trade_count": len(result.trades),
        "net_profit": result.net_profit,
        "ending_balance": result.ending_balance,
        "return_percentage": result.return_percentage,
        "win_rate": result.win_rate,
        "profit_factor": result.profit_factor if isfinite(result.profit_factor) else None,
        "max_drawdown": result.max_drawdown,
    }


if __name__ == "__main__":
    main()
