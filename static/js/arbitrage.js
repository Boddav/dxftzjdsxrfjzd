// Arbitrázs dashboard JavaScript

let arbInterval;

document.addEventListener('DOMContentLoaded', function () {
    refreshArbitrage();
    arbInterval = setInterval(refreshArbitrage, 5000);
});

function showArbMessage(text, type) {
    // textContent (nem innerHTML) - a szöveg tartalmazhat szerver által
    // visszaadott hibaüzenetet (pl. bróker nevet), amit sosem szabad
    // HTML-ként értelmezni.
    const el = document.getElementById('arbMessage');
    el.textContent = '';
    const div = document.createElement('div');
    div.className = `message ${type}`;
    div.textContent = text;
    el.appendChild(div);
    setTimeout(() => { el.textContent = ''; }, 4000);
}

async function refreshArbitrage() {
    try {
        const resp = await fetch('/api/arbitrage/status');
        const data = await resp.json();
        if (!data.success) return;

        const statusEl = document.getElementById('arbStatus');
        statusEl.innerHTML = data.running
            ? '<span class="status-indicator online"></span> Fut'
            : '<span class="status-indicator offline"></span> Leállítva';
        document.getElementById('arbStartBtn').disabled = data.running;
        document.getElementById('arbStopBtn').disabled = !data.running;

        document.getElementById('arbBrokerCount').textContent = data.brokers.length;
        document.getElementById('arbOpenCount').textContent = data.open_pairs.length;
        const pnl = data.daily_realized_estimate || 0;
        const pnlEl = document.getElementById('arbDailyPnl');
        pnlEl.textContent = pnl.toFixed(2);
        pnlEl.className = 'stat-value ' + (pnl >= 0 ? 'text-success' : 'text-danger');

        if (data.last_error) {
            showArbMessage(`⚠️ ${data.last_error}`, 'error');
        }

        renderBrokers(data.brokers);
        fillConfigForm(data.config);
        renderPrices(data.prices);
        renderOpenPairs(data.open_pairs);
        renderClosedPairs(data.closed_pairs);
    } catch (e) {
        console.error('Arbitrázs státusz lekérési hiba:', e);
    }
}

function renderBrokers(brokers) {
    const tbody = document.getElementById('brokersTableBody');
    if (!brokers.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="no-data">Nincs bekötött bróker</td></tr>';
        return;
    }
    tbody.innerHTML = '';
    brokers.forEach(b => {
        const tr = document.createElement('tr');
        const nameTd = document.createElement('td');
        nameTd.textContent = b.name;
        const accTd = document.createElement('td');
        accTd.textContent = b.account_id || '-';
        const statusTd = document.createElement('td');
        statusTd.textContent = b.enabled ? 'Engedélyezve' : 'Letiltva';
        const actionTd = document.createElement('td');

        const toggleBtn = document.createElement('button');
        toggleBtn.className = 'btn btn-secondary';
        toggleBtn.textContent = b.enabled ? 'Letiltás' : 'Engedélyezés';
        toggleBtn.onclick = () => toggleBroker(b.name, !b.enabled);

        const delBtn = document.createElement('button');
        delBtn.className = 'btn btn-danger';
        delBtn.textContent = 'Törlés';
        delBtn.style.marginLeft = '6px';
        delBtn.onclick = () => deleteBroker(b.name);

        actionTd.appendChild(toggleBtn);
        actionTd.appendChild(delBtn);

        tr.appendChild(nameTd);
        tr.appendChild(accTd);
        tr.appendChild(statusTd);
        tr.appendChild(actionTd);
        tbody.appendChild(tr);
    });
}

function renderPrices(prices) {
    const tbody = document.getElementById('pricesTableBody');
    const rows = [];
    Object.keys(prices || {}).forEach(symbol => {
        Object.keys(prices[symbol]).forEach(broker => {
            const p = prices[symbol][broker];
            rows.push({ symbol, broker, bid: p.bid, ask: p.ask });
        });
    });
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="no-data">Nincs adat</td></tr>';
        return;
    }
    tbody.innerHTML = '';
    rows.forEach(r => {
        const tr = document.createElement('tr');
        [r.symbol, r.broker, r.bid, r.ask].forEach(val => {
            const td = document.createElement('td');
            td.textContent = val;
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

function renderOpenPairs(pairs) {
    const tbody = document.getElementById('openPairsTableBody');
    if (!pairs.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="no-data">Nincs nyitott pár</td></tr>';
        return;
    }
    tbody.innerHTML = '';
    pairs.forEach(p => {
        const tr = document.createElement('tr');
        const vals = [
            p.symbol, p.buy_broker, p.sell_broker, p.lots,
            (p.open_diff_pct !== undefined ? p.open_diff_pct.toFixed(3) : '-'),
            new Date(p.opened_at).toLocaleString('hu-HU'),
        ];
        vals.forEach(val => {
            const td = document.createElement('td');
            td.textContent = val;
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

function renderClosedPairs(pairs) {
    const tbody = document.getElementById('closedPairsTableBody');
    if (!pairs.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="no-data">Nincs előzmény</td></tr>';
        return;
    }
    tbody.innerHTML = '';
    pairs.forEach(p => {
        const tr = document.createElement('tr');
        const openDiff = p.open_diff_pct !== undefined && p.open_diff_pct !== null ? p.open_diff_pct.toFixed(3) : '-';
        const closeDiff = p.close_diff_pct !== undefined && p.close_diff_pct !== null ? p.close_diff_pct.toFixed(3) : '-';
        const vals = [
            p.symbol,
            `${p.buy_broker} / ${p.sell_broker}`,
            `${openDiff} → ${closeDiff}`,
            p.close_reason,
            p.closed_at ? new Date(p.closed_at).toLocaleString('hu-HU') : '-',
        ];
        vals.forEach(val => {
            const td = document.createElement('td');
            td.textContent = val;
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

let configFormFilled = false;
function fillConfigForm(cfg) {
    if (configFormFilled || !cfg) return;
    document.getElementById('arbSymbols').value = (cfg.symbols || []).join(',');
    document.getElementById('arbOpenThreshold').value = cfg.open_threshold_pct;
    document.getElementById('arbCloseThreshold').value = cfg.close_threshold_pct;
    document.getElementById('arbLots').value = cfg.lots;
    document.getElementById('arbTimeout').value = cfg.safety_timeout_minutes;
    document.getElementById('arbDailyLoss').value = cfg.daily_loss_limit_usd;
    document.getElementById('arbAutoExecute').checked = !!cfg.auto_execute;
    configFormFilled = true;
}

async function saveArbConfig() {
    const symbols = document.getElementById('arbSymbols').value.split(',').map(s => s.trim()).filter(Boolean);
    const payload = {
        symbols,
        open_threshold_pct: parseFloat(document.getElementById('arbOpenThreshold').value),
        close_threshold_pct: parseFloat(document.getElementById('arbCloseThreshold').value),
        lots: parseFloat(document.getElementById('arbLots').value),
        safety_timeout_minutes: parseFloat(document.getElementById('arbTimeout').value),
        daily_loss_limit_usd: parseFloat(document.getElementById('arbDailyLoss').value),
        auto_execute: document.getElementById('arbAutoExecute').checked,
    };
    try {
        const resp = await fetch('/api/arbitrage/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await resp.json();
        showArbMessage(data.success ? '✅ Beállítások mentve' : `❌ ${data.message}`, data.success ? 'success' : 'error');
    } catch (e) {
        showArbMessage(`❌ ${e}`, 'error');
    }
}

async function addBroker() {
    const name = document.getElementById('newBrokerName').value.trim();
    if (!name) {
        showArbMessage('❌ Adj meg egy bróker nevet', 'error');
        return;
    }
    if (!/^[a-zA-Z0-9_-]+$/.test(name)) {
        showArbMessage('❌ A bróker név csak betűket, számokat, "-" és "_" karaktereket tartalmazhat', 'error');
        return;
    }
    window.open(`/oauth-setup?broker=${encodeURIComponent(name)}`, '_blank');
}

async function toggleBroker(name, enabled) {
    try {
        const resp = await fetch('/api/arbitrage/brokers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, enabled }),
        });
        const data = await resp.json();
        if (data.success) refreshArbitrage();
        else showArbMessage(`❌ ${data.message}`, 'error');
    } catch (e) {
        showArbMessage(`❌ ${e}`, 'error');
    }
}

async function deleteBroker(name) {
    if (!confirm(`Biztosan törlöd a(z) "${name}" brókert?`)) return;
    try {
        const resp = await fetch(`/api/arbitrage/brokers/${encodeURIComponent(name)}`, { method: 'DELETE' });
        const data = await resp.json();
        if (data.success) refreshArbitrage();
        else showArbMessage(`❌ ${data.message}`, 'error');
    } catch (e) {
        showArbMessage(`❌ ${e}`, 'error');
    }
}

async function startArbitrage() {
    try {
        const resp = await fetch('/api/arbitrage/start', { method: 'POST' });
        const data = await resp.json();
        if (data.success) { showArbMessage('✅ Arbitrázs motor elindítva', 'success'); refreshArbitrage(); }
        else showArbMessage(`❌ ${data.message}`, 'error');
    } catch (e) {
        showArbMessage(`❌ ${e}`, 'error');
    }
}

async function stopArbitrage() {
    try {
        const resp = await fetch('/api/arbitrage/stop', { method: 'POST' });
        const data = await resp.json();
        if (data.success) { showArbMessage('⏹ Arbitrázs motor leállítva', 'success'); refreshArbitrage(); }
        else showArbMessage(`❌ ${data.message}`, 'error');
    } catch (e) {
        showArbMessage(`❌ ${e}`, 'error');
    }
}
