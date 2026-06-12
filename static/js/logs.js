// Logs JavaScript

document.addEventListener('DOMContentLoaded', function() {
    refreshLogs();

    // Automatikus frissítés 10 másodpercenként
    setInterval(refreshLogs, 10000);
});

async function refreshLogs() {
    try {
        const response = await fetch('/api/logs');
        const data = await response.json();

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
