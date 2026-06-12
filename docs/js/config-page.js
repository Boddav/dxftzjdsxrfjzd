// Config Page JavaScript - GitHub Pages Version

document.addEventListener('DOMContentLoaded', function() {
    document.getElementById('currentApiUrl').textContent = API_CONFIG.baseURL;
    checkConnection();
    loadConfig();
});

async function checkConnection() {
    const statusEl = document.getElementById('connectionStatus');
    const textEl = document.getElementById('connectionText');

    try {
        await apiCall('/api/status');
        statusEl.className = 'connection-status connected';
        statusEl.querySelector('.status-indicator').className = 'status-indicator online';
        textEl.textContent = 'Kapcsolódva a backend API-hoz';
    } catch (error) {
        statusEl.className = 'connection-status disconnected';
        statusEl.querySelector('.status-indicator').className = 'status-indicator offline';
        textEl.textContent = 'Nincs kapcsolat a backend API-val';
        console.error('API connection failed:', error);
    }
}

async function loadConfig() {
    try {
        const config = await apiCall('/api/config');

        document.getElementById('clientId').value = config.ctrader_client_id || '';
        document.getElementById('accountId').value = config.account_id || '';
        document.getElementById('maxPositions').value = config.max_positions || '3';
        document.getElementById('riskPerTrade').value = config.risk_per_trade || '1.0';

        // Anthropic API státusz
        const statusBadge = document.getElementById('anthropicStatus');
        if (config.has_anthropic_key) {
            statusBadge.textContent = 'Konfigurálva ✓';
            statusBadge.className = 'badge success';
        } else {
            statusBadge.textContent = 'Nincs beállítva ✗';
            statusBadge.className = 'badge error';
        }

    } catch (error) {
        console.error('Hiba a konfiguráció betöltésekor:', error);
        const statusBadge = document.getElementById('anthropicStatus');
        statusBadge.textContent = 'Hiba';
        statusBadge.className = 'badge error';
    }
}
