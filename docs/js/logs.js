// Logs JavaScript - GitHub Pages Version

let connectionOk = false;

document.addEventListener('DOMContentLoaded', function() {
    checkConnection();
    refreshLogs();

    // Automatikus frissítés 10 másodpercenként
    setInterval(refreshLogs, 10000);
});

async function checkConnection() {
    const statusEl = document.getElementById('connectionStatus');
    const textEl = document.getElementById('connectionText');

    try {
        await apiCall('/api/status');
        connectionOk = true;
        statusEl.className = 'connection-status connected';
        statusEl.querySelector('.status-indicator').className = 'status-indicator online';
        textEl.textContent = 'Kapcsolódva a backend API-hoz';
    } catch (error) {
        connectionOk = false;
        statusEl.className = 'connection-status disconnected';
        statusEl.querySelector('.status-indicator').className = 'status-indicator offline';
        textEl.textContent = 'Nincs kapcsolat a backend API-val';
        console.error('API connection failed:', error);
    }
}

async function refreshLogs() {
    if (!connectionOk) {
        await checkConnection();
        if (!connectionOk) return;
    }

    try {
        const data = await apiCall('/api/logs');

        const container = document.getElementById('logsContainer');

        if (data.success && data.logs && data.logs.length > 0) {
            container.innerHTML = data.logs.map(line => {
                const level = detectLogLevel(line);
                return `<div class="log-line ${level}">${escapeHtml(line)}</div>`;
            }).join('');

            // Scroll to bottom
            container.scrollTop = container.scrollHeight;
        } else {
            container.innerHTML = '<div class="no-data">Nincs naplóbejegyzés</div>';
        }
    } catch (error) {
        console.error('Naplók betöltési hiba:', error);
        connectionOk = false;
    }
}

function detectLogLevel(line) {
    if (line.includes('ERROR')) return 'ERROR';
    if (line.includes('WARNING')) return 'WARNING';
    if (line.includes('INFO')) return 'INFO';
    return 'INFO';
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
