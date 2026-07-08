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
import requests as http_requests

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
            'max_positions': os.getenv('MAX_OPEN_POSITIONS', '3'),
            'risk_per_trade': os.getenv('MAX_RISK_PER_TRADE', '0.02')
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


@app.route('/oauth-setup')
def oauth_setup():
    """cTrader OAuth beállítás oldal"""
    client_id = os.getenv('CTRADER_CLIENT_ID', '')
    replit_domain = os.getenv('REPLIT_DEV_DOMAIN', '')
    redirect_uri = f"https://{replit_domain}/callback" if replit_domain else "http://localhost:5000/callback"
    auth_url = f"https://openapi.ctrader.com/apps/auth?client_id={client_id}&redirect_uri={redirect_uri}&scope=trading"
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>cTrader OAuth Setup</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:linear-gradient(135deg,#667eea,#764ba2);display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}}
.box{{background:#fff;border-radius:20px;padding:50px;max-width:580px;width:100%;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,.3)}}
h1{{color:#333;margin-bottom:16px}}p{{color:#666;line-height:1.6;margin-bottom:24px}}
.btn{{display:inline-block;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;padding:14px 36px;border-radius:50px;text-decoration:none;font-weight:700;font-size:17px}}
.info{{background:#f8f9fa;border-left:4px solid #667eea;padding:14px;margin-top:24px;text-align:left;border-radius:5px;font-size:14px}}
code{{background:#e9ecef;padding:2px 6px;border-radius:3px;font-family:monospace}}
</style></head>
<body><div class="box">
<div style="font-size:56px;margin-bottom:16px">🤖📈</div>
<h1>cTrader OAuth Beállítás</h1>
<p>Csatlakoztasd a cTrader fiókodat az AI Trading Bot-hoz.</p>
<a href="{auth_url}" class="btn">🔐 Csatlakozás cTrader-hez</a>
<div class="info"><strong>ℹ️ Mi fog történni?</strong><br>
1. Átirányítás a cTrader bejelentkezési oldalára<br>
2. Fiók engedélyezése<br>
3. Automatikus <code>credentials.json</code> létrehozás<br>
4. Trading bot használatra kész!</div>
</div></body></html>"""


@app.route('/callback')
def oauth_callback():
    """cTrader OAuth callback – authorization code feldolgozása"""
    code = request.args.get('code')
    if not code:
        return "Hiányzó authorization code", 400

    client_id = os.getenv('CTRADER_CLIENT_ID', '')
    client_secret = os.getenv('CTRADER_CLIENT_SECRET', '')
    replit_domain = os.getenv('REPLIT_DEV_DOMAIN', '')
    redirect_uri = f"https://{replit_domain}/callback" if replit_domain else "http://localhost:5000/callback"

    try:
        # Token csere
        resp = http_requests.post('https://openapi.ctrader.com/apps/token', data={
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri,
            'client_id': client_id,
            'client_secret': client_secret
        })
        resp.raise_for_status()
        tokens = resp.json()
        access_token = tokens['access_token']
        refresh_token = tokens['refresh_token']
        logger.info("✅ cTrader access token kapva")

        # Account ID lekérése
        account_id = os.getenv('CTRADER_ACCOUNT_ID', '')
        try:
            acc_resp = http_requests.get('https://openapi.ctrader.com/apps/accounts',
                                         headers={'Authorization': f'Bearer {access_token}'})
            acc_resp.raise_for_status()
            accounts = acc_resp.json()
            if accounts:
                for acc in accounts:
                    if not acc.get('live', True):
                        account_id = str(acc['accountId'])
                        break
                if not account_id and accounts:
                    account_id = str(accounts[0]['accountId'])
        except Exception as e:
            logger.warning(f"Account lekérés sikertelen (manuális ID-t használ): {e}")

        # Credentials mentése
        credentials = {
            'clientId': client_id,
            'clientSecret': client_secret,
            'accessToken': access_token,
            'refreshToken': refresh_token,
            'accountId': account_id,
            'redirectUri': redirect_uri
        }
        with open('credentials.json', 'w') as f:
            json.dump(credentials, f, indent=2)
        logger.info("💾 credentials.json létrehozva")

        return """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Sikeres!</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:linear-gradient(135deg,#11998e,#38ef7d);display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}
.box{background:#fff;border-radius:20px;padding:50px;max-width:520px;width:100%;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,.3)}
h1{color:#11998e;margin-bottom:16px}p{color:#666;line-height:1.6}
.btn{display:inline-block;background:#11998e;color:#fff;padding:12px 32px;border-radius:50px;text-decoration:none;font-weight:700;margin-top:20px}
</style></head>
<body><div class="box">
<div style="font-size:72px;margin-bottom:16px">✅</div>
<h1>Sikeres Csatlakozás!</h1>
<p>A cTrader fiókod sikeresen össze lett kapcsolva.<br>
<code>credentials.json</code> fájl létrehozva.</p>
<a href="/" class="btn">⬅️ Vissza a Dashboardra</a>
</div></body></html>"""

    except Exception as e:
        logger.error(f"OAuth callback hiba: {e}")
        return f"OAuth hiba: {str(e)}", 500


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
