// Config JavaScript

let _allSymbols = ['XAUUSD'];
let _selectedSymbols = new Set(['XAUUSD']);

document.addEventListener('DOMContentLoaded', function() {
    loadConfig();
});

async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        const config = await response.json();

        document.getElementById('accountId').value = config.account_id || '';
        document.getElementById('maxPositions').value = config.max_positions || '3';
        document.getElementById('riskPerTrade').value = config.risk_per_trade || '1.0';
        document.getElementById('cycleInterval').value = config.cycle_interval || '60';
        document.getElementById('symbolDelay').value = config.symbol_delay || '15';

        // Placeholder az érzékeny Anthropic kulcshoz
        document.getElementById('anthropicKey').placeholder = config.has_anthropic_key ?
            '••••••••••••' : 'Nincs beállítva';

        // A jelenleg kiválasztott szimbólumokat megőrizzük, függetlenül attól,
        // hogy utána sikerül-e élő listát betölteni.
        _selectedSymbols = new Set(config.trading_symbols || ['XAUUSD']);
        // Amíg az élő lista be nem töltődik (vagy ha az sikertelen), a
        // statikus fallback listát mutatjuk, hogy a mentés se essen szét.
        _allSymbols = config.available_symbols || ['XAUUSD'];
        renderSymbols();

        await loadAvailableSymbols();

    } catch (error) {
        showMessage('Hiba a konfiguráció betöltésekor', 'error');
        console.error(error);
    }
}

async function loadAvailableSymbols() {
    const infoEl = document.getElementById('symbolsListInfo');
    try {
        const response = await fetch('/api/symbols');
        const data = await response.json();
        if (data.success && Array.isArray(data.symbols) && data.symbols.length) {
            _allSymbols = data.symbols;
        }
        if (data.source === 'static') {
            infoEl.textContent = data.message || 'Nincs élő cTrader kapcsolat - a szűkített alapértelmezett lista jelenik meg.';
            infoEl.className = 'message error';
            infoEl.style.display = 'block';
        } else {
            infoEl.style.display = 'none';
        }
        renderSymbols();
    } catch (error) {
        // Az élő lista nem elérhető - marad a konfigurációból kapott
        // statikus fallback lista, amit a loadConfig() már beállított.
        infoEl.textContent = 'Nem sikerült lekérni a bróker élő szimbólumlistáját - a szűkített alapértelmezett lista jelenik meg.';
        infoEl.className = 'message error';
        infoEl.style.display = 'block';
        console.error(error);
    }
}

function renderSymbols() {
    const listEl = document.getElementById('symbolsList');
    const query = (document.getElementById('symbolSearch').value || '').trim().toUpperCase();
    const filtered = query ? _allSymbols.filter(sym => sym.toUpperCase().includes(query)) : _allSymbols;

    // FONTOS: a szimbólumnevek a brókertől érkező, nem megbízható adatok -
    // biztonságos DOM-építést használunk (createElement/textContent) az
    // innerHTML-be fűzés helyett, hogy egy rosszindulatú/hibás szimbólumnév
    // se tudjon HTML/script injektálást okozni.
    listEl.replaceChildren();

    if (!filtered.length) {
        const empty = document.createElement('p');
        empty.className = 'checkbox-item';
        empty.textContent = 'Nincs a keresésnek megfelelő szimbólum.';
        listEl.appendChild(empty);
        return;
    }

    for (const sym of filtered) {
        const label = document.createElement('label');
        label.className = 'checkbox-item';

        const input = document.createElement('input');
        input.type = 'checkbox';
        input.name = 'symbol';
        input.value = sym;
        input.checked = _selectedSymbols.has(sym);
        input.addEventListener('change', () => onSymbolToggle(input));

        label.appendChild(input);
        label.appendChild(document.createTextNode(sym));
        listEl.appendChild(label);
    }
}

function onSymbolToggle(el) {
    if (el.checked) {
        _selectedSymbols.add(el.value);
    } else {
        _selectedSymbols.delete(el.value);
    }
}

function filterSymbols() {
    renderSymbols();
}

async function saveConfig() {
    // FONTOS: nem a DOM-ból olvasunk (querySelectorAll('input[name="symbol"]:checked')),
    // mert a keresés/szűrés miatt a nem látszó (kiszűrt) checkboxok nincsenek
    // a DOM-ban - a _selectedSymbols halmaz tartja számon a kiválasztást
    // szűréstől függetlenül (lásd onSymbolToggle/renderSymbols).
    const selectedSymbols = Array.from(_selectedSymbols);

    if (selectedSymbols.length === 0) {
        showMessage('Legalább egy szimbólumot ki kell választani!', 'error');
        return;
    }

    const config = {
        ctrader_account_id: document.getElementById('accountId').value,
        anthropic_api_key: document.getElementById('anthropicKey').value,
        max_positions: document.getElementById('maxPositions').value,
        risk_per_trade: document.getElementById('riskPerTrade').value,
        cycle_interval: document.getElementById('cycleInterval').value,
        symbol_delay: document.getElementById('symbolDelay').value,
        trading_symbols: selectedSymbols
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
