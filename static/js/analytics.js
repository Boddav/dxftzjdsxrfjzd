// ML szignál minőség + Backtesting JavaScript

document.addEventListener('DOMContentLoaded', function () {
    loadMlQuality();
    loadCachedBacktest();
});

function showAnalyticsMessage(text, type) {
    // textContent (nem innerHTML) - a szöveg szerver-oldali hibaüzenetet
    // tartalmazhat, amit sosem szabad HTML-ként értelmezni.
    const el = document.getElementById('analyticsMessage');
    el.textContent = '';
    const div = document.createElement('div');
    div.className = `message ${type}`;
    div.textContent = text;
    el.appendChild(div);
    setTimeout(() => { el.textContent = ''; }, 5000);
}

function fmtPct(v) {
    return v === null || v === undefined ? '-' : `${(v * 100).toFixed(1)}%`;
}

async function loadMlQuality() {
    try {
        const symbol = document.getElementById('mlQualitySymbol').value.trim();
        const url = symbol ? `/api/ml-quality?symbol=${encodeURIComponent(symbol)}` : '/api/ml-quality';
        const resp = await fetch(url);
        const data = await resp.json();
        if (!data.success) {
            showAnalyticsMessage(data.message || 'Hiba az ML minőség lekérésekor', 'error');
            return;
        }
        const live = data.live;
        document.getElementById('mlResolvedCount').textContent = live.directional_count;
        document.getElementById('mlAccuracy').textContent = fmtPct(live.accuracy);
        document.getElementById('mlRecentAccuracy').textContent = fmtPct(live.recent_accuracy);
        document.getElementById('mlPendingCount').textContent = live.pending_count;

        const tbody = document.getElementById('mlBySymbolTableBody');
        tbody.textContent = '';
        const symbols = Object.keys(live.by_symbol || {});
        if (symbols.length === 0) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 4;
            td.className = 'no-data';
            td.textContent = 'Nincs adat';
            tr.appendChild(td);
            tbody.appendChild(tr);
        } else {
            symbols.forEach(sym => {
                const s = live.by_symbol[sym];
                const tr = document.createElement('tr');
                [sym, s.directional_count, fmtPct(s.accuracy), fmtPct(s.recent_accuracy)].forEach(val => {
                    const td = document.createElement('td');
                    td.textContent = val;
                    tr.appendChild(td);
                });
                tbody.appendChild(tr);
            });
        }
    } catch (e) {
        showAnalyticsMessage(`Hálózati hiba: ${e.message}`, 'error');
    }
}

async function runHistoricalEval() {
    try {
        const symbol = document.getElementById('histSymbol').value.trim().toUpperCase();
        const count = document.getElementById('histCount').value;
        if (!symbol) {
            showAnalyticsMessage('Adj meg egy szimbólumot!', 'error');
            return;
        }
        const resp = await fetch(`/api/ml-quality?symbol=${encodeURIComponent(symbol)}&historical=1&count=${encodeURIComponent(count)}`);
        const data = await resp.json();
        if (!data.success || !data.historical) {
            showAnalyticsMessage(data.message || 'Hiba a historikus kiértékeléskor', 'error');
            return;
        }
        const h = data.historical;
        const tbody = document.getElementById('histResultTableBody');
        tbody.textContent = '';
        const tr = document.createElement('tr');
        [
            `${h.train_candles} / ${h.test_candles}`,
            fmtPct(h.accuracy),
            h.precision === null ? '-' : h.precision,
            h.recall === null ? '-' : h.recall,
            h.f1 === null ? '-' : h.f1,
            fmtPct(h.baseline_up_rate),
        ].forEach(val => {
            const td = document.createElement('td');
            td.textContent = val;
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
        showAnalyticsMessage('Historikus kiértékelés kész.', 'success');
    } catch (e) {
        showAnalyticsMessage(`Hálózati hiba: ${e.message}`, 'error');
    }
}

async function loadCachedBacktest() {
    try {
        const symbol = document.getElementById('btSymbol').value.trim().toUpperCase();
        const resp = await fetch('/api/backtest/results');
        const data = await resp.json();
        if (data.success && data.results && data.results[symbol]) {
            renderBacktestResult(data.results[symbol]);
        }
    } catch (e) {
        // Csendben elnyeljük - ez csak egy kényelmi előtöltés, nem kritikus.
    }
}

async function runBacktest() {
    const btn = document.getElementById('btRunBtn');
    btn.disabled = true;
    btn.textContent = '⏳ Fut...';
    try {
        const payload = {
            symbol: document.getElementById('btSymbol').value.trim().toUpperCase(),
            timeframe: document.getElementById('btTimeframe').value,
            candle_count: parseInt(document.getElementById('btCount').value, 10),
            stop_loss_pips: parseFloat(document.getElementById('btSl').value),
            take_profit_pips: parseFloat(document.getElementById('btTp').value),
            spread_pips: parseFloat(document.getElementById('btSpread').value),
            slippage_pips: parseFloat(document.getElementById('btSlippage').value),
            min_hold_bars: parseInt(document.getElementById('btMinHold').value, 10),
        };
        if (!payload.symbol) {
            showAnalyticsMessage('Adj meg egy szimbólumot!', 'error');
            return;
        }
        const resp = await fetch('/api/backtest/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (!data.success) {
            showAnalyticsMessage(data.message || 'Hiba a backteszt futtatásakor', 'error');
            return;
        }
        renderBacktestResult(data.result);
        showAnalyticsMessage('Backtest lefutott.', 'success');
    } catch (e) {
        showAnalyticsMessage(`Hálózati hiba: ${e.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = '▶ Backtest futtatása';
    }
}

function renderBacktestResult(result) {
    document.getElementById('btTrades').textContent = result.total_trades;
    document.getElementById('btWinRate').textContent = fmtPct(result.win_rate);
    document.getElementById('btPnl').textContent = result.total_pnl_pips;
    document.getElementById('btProfitFactor').textContent = result.profit_factor === null ? '-' : result.profit_factor;
    document.getElementById('btDrawdown').textContent = result.max_drawdown_pct === undefined ? '-' : `${result.max_drawdown_pct}%`;
    document.getElementById('btSharpe').textContent = result.sharpe_ratio === null || result.sharpe_ratio === undefined ? '-' : result.sharpe_ratio;
    document.getElementById('btSortino').textContent = result.sortino_ratio === null || result.sortino_ratio === undefined ? '-' : result.sortino_ratio;
    document.getElementById('btCalmar').textContent = result.calmar_ratio === null || result.calmar_ratio === undefined ? '-' : result.calmar_ratio;
    const longWr = result.long_win_rate === null || result.long_win_rate === undefined ? '-' : fmtPct(result.long_win_rate);
    const shortWr = result.short_win_rate === null || result.short_win_rate === undefined ? '-' : fmtPct(result.short_win_rate);
    document.getElementById('btLongShort').textContent = `${longWr} / ${shortWr}`;
    document.getElementById('btAvgHold').textContent = result.avg_holding_bars === null || result.avg_holding_bars === undefined ? '-' : result.avg_holding_bars;

    const tbody = document.getElementById('btTradesTableBody');
    tbody.textContent = '';
    const trades = result.trades || [];
    if (trades.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 5;
        td.className = 'no-data';
        td.textContent = 'Nincs kereskedés ebben a backtesztben';
        tr.appendChild(td);
        tbody.appendChild(tr);
    } else {
        // Legutóbbi 50 megjelenítve, hogy ne legyen kezelhetetlenül hosszú a táblázat.
        trades.slice(-50).reverse().forEach(t => {
            const tr = document.createElement('tr');
            [t.direction, t.entry_time || '-', t.exit_time || '-', t.exit_reason, t.pnl_pips].forEach(val => {
                const td = document.createElement('td');
                td.textContent = val;
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
    }

    drawEquityCurve(result.equity_curve || []);
}

function drawEquityCurve(points) {
    const canvas = document.getElementById('btEquityCanvas');
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (!points || points.length < 2) {
        ctx.fillStyle = '#8b949e';
        ctx.font = '14px sans-serif';
        ctx.fillText('Nincs elég adat a görbéhez', 20, canvas.height / 2);
        return;
    }

    const values = points.map(p => p.pnl_pips);
    const min = Math.min(0, ...values);
    const max = Math.max(0, ...values);
    const range = (max - min) || 1;
    const padding = 20;
    const w = canvas.width - padding * 2;
    const h = canvas.height - padding * 2;

    // Nulla vonal
    const zeroY = padding + h - ((0 - min) / range) * h;
    ctx.strokeStyle = '#30363d';
    ctx.beginPath();
    ctx.moveTo(padding, zeroY);
    ctx.lineTo(canvas.width - padding, zeroY);
    ctx.stroke();

    ctx.strokeStyle = values[values.length - 1] >= 0 ? '#3fb950' : '#f85149';
    ctx.lineWidth = 2;
    ctx.beginPath();
    points.forEach((p, i) => {
        const x = padding + (i / (points.length - 1)) * w;
        const y = padding + h - ((p.pnl_pips - min) / range) * h;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.stroke();
}
