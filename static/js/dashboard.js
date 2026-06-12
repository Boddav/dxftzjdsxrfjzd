// Dashboard JavaScript

let statusInterval;

// Oldal betöltésekor
document.addEventListener('DOMContentLoaded', function() {
    updateStatus();
    loadPositions();
    loadHistory();

    // Automatikus frissítés 5 másodpercenként
    statusInterval = setInterval(updateStatus, 5000);
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

        if (data.success && data.history && data.history.length > 0) {
            const recent = data.history.slice(-10).reverse();
            tbody.innerHTML = recent.map(trade => `
                <tr>
                    <td>${formatTime(trade.timestamp)}</td>
                    <td>${trade.symbol}</td>
                    <td>${trade.type}</td>
                    <td><strong>${trade.action}</strong></td>
                    <td class="${trade.pnl >= 0 ? 'text-success' : 'text-danger'}">
                        ${trade.pnl ? formatCurrency(trade.pnl) : '-'}
                    </td>
                    <td>${trade.reasoning || '-'}</td>
                </tr>
            `).join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="6" class="no-data">Nincs előzmény</td></tr>';
        }
    } catch (error) {
        console.error('Előzmények betöltési hiba:', error);
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
    // Egyszerű értesítés (később lehet alert helyett toast)
    alert(message);
}
