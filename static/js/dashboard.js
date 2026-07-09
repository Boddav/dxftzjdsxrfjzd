// Dashboard JavaScript

let statusInterval;

// Oldal betöltésekor
document.addEventListener('DOMContentLoaded', function() {
    updateStatus();
    loadPositions();
    loadHistory();
    loadAiDecisions();

    // Automatikus frissítés - a pozíciók lekérése minden hívásnál élő
    // árfolyam-lekérést (spot subscribe) is indít a cTrader API felé, ezért
    // 5s helyett 15s a frissítési intervallum, hogy ne terheljük feleslegesen
    // az API-t (ez a cTrader hívásokra vonatkozik, nem a Claude/Anthropic
    // hívásokra - azok a bot saját, tőle független 1 perces ciklusában futnak).
    statusInterval = setInterval(() => {
        updateStatus();
        loadPositions();
        loadAiDecisions();
    }, 15000);
});

// Bot státusz frissítése
async function updateStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();

        const statusElement = document.getElementById('botStatus');
        const statusIndicator = statusElement.querySelector('.status-indicator');

        if (data.running) {
            statusElement.innerHTML = '<span class="status-indicator online"></span> Fut';
            document.getElementById('startBtn').disabled = true;
            document.getElementById('stopBtn').disabled = false;
        } else {
            statusElement.innerHTML = '<span class="status-indicator offline"></span> Leállítva';
            document.getElementById('startBtn').disabled = false;
            document.getElementById('stopBtn').disabled = true;
        }

        document.getElementById('tradesToday').textContent = data.trades_today || 0;
        document.getElementById('pnlToday').textContent = formatCurrency(data.pnl_today || 0);
        document.getElementById('activePositions').textContent = data.positions?.length || 0;

    } catch (error) {
        console.error('Státusz frissítési hiba:', error);
    }
}

// Bot indítása
async function startBot() {
    try {
        const response = await fetch('/api/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        const data = await response.json();

        if (data.success) {
            showNotification('Bot sikeresen elindítva', 'success');
            updateStatus();
        } else {
            showNotification(data.message, 'error');
        }
    } catch (error) {
        showNotification('Hiba a bot indításakor', 'error');
        console.error(error);
    }
}

// Bot leállítása
async function stopBot() {
    if (!confirm('Biztosan leállítod a botot?')) {
        return;
    }

    try {
        const response = await fetch('/api/stop', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        const data = await response.json();

        if (data.success) {
            showNotification('Bot sikeresen leállítva', 'success');
            updateStatus();
        } else {
            showNotification(data.message, 'error');
        }
    } catch (error) {
        showNotification('Hiba a bot leállításakor', 'error');
        console.error(error);
    }
}

// Pozíciók betöltése
async function loadPositions() {
    try {
        const response = await fetch('/api/positions');
        const data = await response.json();

        const tbody = document.getElementById('positionsBody');

        if (data.success && data.positions && data.positions.length > 0) {
            tbody.innerHTML = data.positions.map(pos => `
                <tr>
                    <td>${pos.symbol}</td>
                    <td>${pos.type}</td>
                    <td>${pos.volume}</td>
                    <td>${pos.openPrice}</td>
                    <td>${pos.currentPrice}</td>
                    <td class="${pos.pnl >= 0 ? 'text-success' : 'text-danger'}">
                        ${formatCurrency(pos.pnl)}
                    </td>
                    <td>${formatTime(pos.openTime)}</td>
                </tr>
            `).join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="7" class="no-data">Nincs aktív pozíció</td></tr>';
        }
    } catch (error) {
        console.error('Pozíciók betöltési hiba:', error);
    }
}

// Előzmények betöltése
async function loadHistory() {
    try {
        const response = await fetch('/api/history');
        const data = await response.json();

        const tbody = document.getElementById('historyBody');

        tbody.innerHTML = '';

        if (data.success && data.history && data.history.length > 0) {
            const recent = data.history.slice(-10).reverse();
            recent.forEach(trade => {
                const tr = document.createElement('tr');

                const tdTime = document.createElement('td');
                tdTime.textContent = formatTime(trade.timestamp);

                const tdSymbol = document.createElement('td');
                tdSymbol.textContent = trade.symbol || '-';

                const tdType = document.createElement('td');
                tdType.textContent = trade.type || '-';

                const tdAction = document.createElement('td');
                const strong = document.createElement('strong');
                strong.textContent = trade.action || '-';
                tdAction.appendChild(strong);

                const tdPnl = document.createElement('td');
                tdPnl.className = trade.pnl >= 0 ? 'text-success' : 'text-danger';
                tdPnl.textContent = trade.pnl != null ? formatCurrency(trade.pnl) : '-';

                const tdReasoning = document.createElement('td');
                // Az indoklás a Claude AI nyers szöveges kimenete - sose
                // innerHTML-lel szúrjuk be, mindig textContent-tel.
                tdReasoning.textContent = trade.reasoning || '-';

                tr.append(tdTime, tdSymbol, tdType, tdAction, tdPnl, tdReasoning);
                tbody.appendChild(tr);
            });
        } else {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 6;
            td.className = 'no-data';
            td.textContent = 'Nincs előzmény';
            tr.appendChild(td);
            tbody.appendChild(tr);
        }
    } catch (error) {
        console.error('Előzmények betöltési hiba:', error);
    }
}

// AI visszajelzések betöltése (minden döntés, HOLD is - nem csak a végrehajtott megbízások)
async function loadAiDecisions() {
    try {
        const response = await fetch('/api/ai-decisions');
        const data = await response.json();

        const tbody = document.getElementById('aiFeedbackBody');
        tbody.innerHTML = '';

        if (data.success && data.decisions && data.decisions.length > 0) {
            const recent = data.decisions.slice(-15).reverse();
            recent.forEach(d => {
                const tr = document.createElement('tr');

                const tdTime = document.createElement('td');
                tdTime.textContent = formatTime(d.timestamp);

                const tdSymbol = document.createElement('td');
                tdSymbol.textContent = d.symbol || '-';

                const tdAction = document.createElement('td');
                const action = d.action || 'HOLD';
                const badge = document.createElement('span');
                // Az action a saját kódunk döntés-listájából jön (BUY/SELL/HOLD),
                // nem közvetlen AI szöveg, de a class-nevet így is védetten építjük.
                badge.className = 'action-badge action-' + action.toLowerCase().replace(/[^a-z]/g, '');
                badge.textContent = action;
                tdAction.appendChild(badge);

                const tdConfidence = document.createElement('td');
                tdConfidence.textContent = d.confidence != null ? Math.round(d.confidence * 100) + '%' : '-';

                const tdReasoning = document.createElement('td');
                // A reasoning a Claude AI nyers szöveges kimenete - sose innerHTML-lel
                // szúrjuk be, mindig textContent-tel, hogy ne lehessen HTML/script
                // injektálás az admin felületen.
                tdReasoning.textContent = d.reasoning || '-';

                tr.append(tdTime, tdSymbol, tdAction, tdConfidence, tdReasoning);
                tbody.appendChild(tr);
            });
        } else {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 5;
            td.className = 'no-data';
            td.textContent = 'Nincs AI visszajelzés';
            tr.appendChild(td);
            tbody.appendChild(tr);
        }
    } catch (error) {
        console.error('AI visszajelzés betöltési hiba:', error);
    }
}

// Segédfüggvények
function formatCurrency(value) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD'
    }).format(value);
}

function formatTime(timestamp) {
    return new Date(timestamp).toLocaleString('hu-HU');
}

function showNotification(message, type) {
    const el = document.getElementById('notification');
    if (el) {
        el.textContent = message;
        el.className = 'notification ' + type;
        el.style.display = 'block';
        setTimeout(() => { el.style.display = 'none'; }, 3000);
    } else {
        alert(message);
    }
}

async function addTestPosition() {
    if (!confirm('Ez egy VALÓS megbízást küld a cTrader demo számládra (EURUSD BUY 0.01 lot). Folytatod?')) {
        return;
    }
    try {
        const response = await fetch('/api/test-position', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ symbol: 'EURUSD', side: 'BUY', lots: 0.01 })
        });
        const data = await response.json();
        if (data.success) {
            showNotification('Teszt megbízás elküldve a demo számlára', 'success');
            loadPositions();
            updateStatus();
        } else {
            showNotification(data.message, 'error');
        }
    } catch (error) {
        showNotification('Hiba a teszt megbízás küldésekor', 'error');
        console.error(error);
    }
}
