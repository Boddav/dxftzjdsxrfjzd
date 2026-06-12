// Config JavaScript

document.addEventListener('DOMContentLoaded', function() {
    loadConfig();
});

async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        const config = await response.json();

        document.getElementById('clientId').value = config.ctrader_client_id || '';
        document.getElementById('accountId').value = config.account_id || '';
        document.getElementById('maxPositions').value = config.max_positions || '3';
        document.getElementById('riskPerTrade').value = config.risk_per_trade || '1.0';

        // Placeholder-ek az érzékeny adatokhoz
        document.getElementById('clientSecret').placeholder = config.has_client_secret ?
            '••••••••••••' : 'Nincs beállítva';
        document.getElementById('anthropicKey').placeholder = config.has_anthropic_key ?
            '••••••••••••' : 'Nincs beállítva';

    } catch (error) {
        showMessage('Hiba a konfiguráció betöltésekor', 'error');
        console.error(error);
    }
}

async function saveConfig() {
    const config = {
        ctrader_client_id: document.getElementById('clientId').value,
        ctrader_client_secret: document.getElementById('clientSecret').value,
        ctrader_account_id: document.getElementById('accountId').value,
        anthropic_api_key: document.getElementById('anthropicKey').value,
        max_positions: document.getElementById('maxPositions').value,
        risk_per_trade: document.getElementById('riskPerTrade').value
    };

    try {
        const response = await fetch('/api/config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(config)
        });

        const data = await response.json();

        if (data.success) {
            showMessage('Konfiguráció sikeresen mentve', 'success');
        } else {
            showMessage(data.message, 'error');
        }
    } catch (error) {
        showMessage('Hiba a konfiguráció mentésekor', 'error');
        console.error(error);
    }
}

function showMessage(message, type) {
    const messageDiv = document.getElementById('configMessage');
    messageDiv.textContent = message;
    messageDiv.className = 'message ' + type;

    setTimeout(() => {
        messageDiv.className = 'message';
    }, 5000);
}
