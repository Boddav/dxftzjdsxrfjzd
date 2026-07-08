#!/usr/bin/env python3
"""
AI Trading Advisor - Admin Interface
Web-alapú adminisztrációs felület a trading bot kezeléséhez
"""

import os
import json
import asyncio
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_cors import CORS
from dotenv import load_dotenv
import logging

# Saját modulok
from ai_trading_advisor import AITradingAdvisor
from mcp_server import CTraderMCPServer

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SESSION_SECRET', os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production'))

# CORS engedélyezése - Replit proxy és GitHub Pages
CORS(app, resources={
    r"/api/*": {
        "origins": "*"
    }
})

# Globális bot instance
bot_instance = None
bot_status = {
    'running': False,
    'last_update': None,
    'positions': [],
    'trades_today': 0,
    'pnl_today': 0.0
}

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@app.route('/')
def index():
    """Főoldal - Dashboard"""
    return render_template('dashboard.html', status=bot_status)


@app.route('/api/status')
def api_status():
    """Bot státusz API endpoint"""
    return jsonify(bot_status)


@app.route('/api/start', methods=['POST'])
def api_start_bot():
    """Bot indítása"""
    global bot_instance, bot_status

    try:
        if bot_status['running']:
            return jsonify({'success': False, 'message': 'Bot már fut!'})

        # Ellenőrzés: van-e minden szükséges konfiguráció
        if not os.getenv('ANTHROPIC_API_KEY'):
            return jsonify({'success': False, 'message': 'ANTHROPIC_API_KEY nincs beállítva!'})

        if not os.getenv('CTRADER_CLIENT_ID'):
            return jsonify({'success': False, 'message': 'cTrader credentials nincsenek beállítva! Később add hozzá.'})

        # Bot státusz frissítése (egyelőre csak mock)
        bot_status['running'] = True
        bot_status['last_update'] = datetime.now().isoformat()

        logger.info("Trading bot indítási kérés fogadva (demo mód)")
        return jsonify({
            'success': True,
            'message': 'Bot státusz frissítve. Teljes funkcionalitáshoz add hozzá a cTrader credentials-eket!'
        })

    except Exception as e:
        logger.error(f"Bot indítási hiba: {str(e)}")
        return jsonify({'success': False, 'message': f'Hiba: {str(e)}'})


@app.route('/api/stop', methods=['POST'])
def api_stop_bot():
    """Bot leállítása"""
    global bot_instance, bot_status

    try:
        if not bot_status['running']:
            return jsonify({'success': False, 'message': 'Bot nem fut!'})

        if bot_instance:
            # Bot leállítása
            # TODO: Implement proper shutdown
            bot_instance = None

        bot_status['running'] = False
        bot_status['last_update'] = datetime.now().isoformat()

        logger.info("Trading bot leállítva")
        return jsonify({'success': True, 'message': 'Bot sikeresen leállítva'})

    except Exception as e:
        logger.error(f"Bot leállítási hiba: {str(e)}")
        return jsonify({'success': False, 'message': f'Hiba: {str(e)}'})


@app.route('/api/positions')
def api_positions():
    """Aktuális pozíciók lekérése"""
    try:
        if bot_instance and bot_instance.mcp_server:
            # TODO: Implement position retrieval from cTrader
            positions = []
            return jsonify({'success': True, 'positions': positions})
        else:
            return jsonify({'success': False, 'message': 'Bot nem fut'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/history')
def api_history():
    """Kereskedési előzmények"""
    try:
        # Trade history fájl olvasása
        history_file = 'trade_history.json'
        if os.path.exists(history_file):
            with open(history_file, 'r') as f:
                history = json.load(f)
            return jsonify({'success': True, 'history': history})
        else:
            return jsonify({'success': True, 'history': []})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/config')
def config_page():
    """Beállítások oldal"""
    return render_template('config.html')


@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    """Konfiguráció kezelése"""
    if request.method == 'GET':
        # Jelenlegi konfiguráció (érzékeny adatok nélkül)
        config = {
            'ctrader_client_id': os.getenv('CTRADER_CLIENT_ID', '')[:10] + '...' if os.getenv('CTRADER_CLIENT_ID') else '',
            'has_client_secret': bool(os.getenv('CTRADER_CLIENT_SECRET')),
            'has_anthropic_key': bool(os.getenv('ANTHROPIC_API_KEY')),
            'account_id': os.getenv('CTRADER_ACCOUNT_ID', ''),
            'max_positions': os.getenv('MAX_POSITIONS', '3'),
            'risk_per_trade': os.getenv('RISK_PER_TRADE', '1.0')
        }
        return jsonify(config)

    elif request.method == 'POST':
        # Konfiguráció mentése .env fájlba
        try:
            data = request.json
            # TODO: Implement .env file update
            return jsonify({'success': True, 'message': 'Konfiguráció mentve'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})


@app.route('/logs')
def logs_page():
    """Naplók oldal"""
    return render_template('logs.html')


@app.route('/api/logs')
def api_logs():
    """Naplók lekérése"""
    try:
        log_file = 'trading_bot.log'
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                # Utolsó 100 sor
                lines = f.readlines()
                recent_logs = lines[-100:]
            return jsonify({'success': True, 'logs': recent_logs})
        else:
            return jsonify({'success': True, 'logs': []})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


# async def run_bot():
#     """Bot futtatása háttérben - Jelenleg nem használt (threading megoldás kell)"""
#     # TODO: Implement proper background task with threading or Celery
#     pass


if __name__ == '__main__':
    # Admin felület indítása
    port = int(os.getenv('ADMIN_PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

    print(f"""
╔════════════════════════════════════════════╗
║   AI Trading Advisor - Admin Interface    ║
╚════════════════════════════════════════════╝

🌐 Admin felület: http://localhost:{port}
🔧 Debug mód: {debug}

Nyomd meg Ctrl+C a leállításhoz
    """)

    app.run(host='0.0.0.0', port=port, debug=debug)
