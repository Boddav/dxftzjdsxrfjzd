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

# config.json betöltése induláskor (felülírja a .env értékeit ha újabb)
_config_file = 'config.json'
if os.path.exists(_config_file):
    with open(_config_file, 'r') as _f:
        for _k, _v in json.load(_f).items():
            if _v:
                os.environ[_k] = _v

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
        return jsonify({'success': True, 'positions': bot_status.get('positions', [])})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/test-position', methods=['POST'])
def api_test_position():
    """Teszt pozíció hozzáadása a dashboardhoz"""
    import random
    symbols = ['XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY']
    symbol = random.choice(symbols)
    side = random.choice(['BUY', 'SELL'])
    open_price = round(random.uniform(1800, 2050) if symbol == 'XAUUSD' else random.uniform(1.05, 1.15), 5)
    current_price = round(open_price + random.uniform(-5, 5) if symbol == 'XAUUSD' else open_price + random.uniform(-0.005, 0.005), 5)
    pnl = round((current_price - open_price) * (1 if side == 'BUY' else -1) * 100, 2)

    pos = {
        'id': random.randint(10000, 99999),
        'symbol': symbol,
        'type': side,
        'volume': round(random.uniform(0.01, 0.1), 2),
        'openPrice': open_price,
        'currentPrice': current_price,
        'pnl': pnl,
        'openTime': datetime.now().isoformat()
    }
    bot_status['positions'].append(pos)
    bot_status['last_update'] = datetime.now().isoformat()
    logger.info(f"Teszt pozíció hozzáadva: {symbol} {side} @ {open_price}")
    return jsonify({'success': True, 'position': pos})


@app.route('/api/clear-positions', methods=['POST'])
def api_clear_positions():
    """Összes pozíció törlése"""
    bot_status['positions'] = []
    return jsonify({'success': True})


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
        try:
            data = request.json or {}
            config_file = 'config.json'

            # Meglévő config betöltése
            saved = {}
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    saved = json.load(f)

            # Mezők frissítése (üres értékeket nem írjuk felül)
            field_map = {
                'ctrader_client_id':     'CTRADER_CLIENT_ID',
                'ctrader_client_secret': 'CTRADER_CLIENT_SECRET',
                'ctrader_account_id':    'CTRADER_ACCOUNT_ID',
                'anthropic_api_key':     'ANTHROPIC_API_KEY',
                'max_positions':         'MAX_OPEN_POSITIONS',
                'risk_per_trade':        'MAX_RISK_PER_TRADE',
            }
            for form_key, env_key in field_map.items():
                val = data.get(form_key, '').strip()
                if val:
                    saved[env_key] = val
                    os.environ[env_key] = val  # azonnal érvényes a futó processben

            with open(config_file, 'w') as f:
                json.dump(saved, f, indent=2)

            logger.info(f"Konfiguráció mentve: {list(saved.keys())}")
            return jsonify({'success': True, 'message': 'Konfiguráció sikeresen mentve!'})
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


OAUTH_REDIRECT_URI_LOCALHOST = "http://localhost:8080/callback"


def _get_redirect_uri():
    """Visszaadja a helyes redirect URI-t (Replit vagy localhost)."""
    replit_domain = os.getenv('REPLIT_DEV_DOMAIN', '')
    if replit_domain:
        return f"https://{replit_domain}/callback"
    return OAUTH_REDIRECT_URI_LOCALHOST


def _exchange_code_for_tokens(code, redirect_uri=None):
    """Authorization code cseréje tokenekre. Visszaadja a credentials dict-et vagy dob kivételt."""
    client_id = os.getenv('CTRADER_CLIENT_ID', '')
    client_secret = os.getenv('CTRADER_CLIENT_SECRET', '')
    if redirect_uri is None:
        redirect_uri = _get_redirect_uri()

    resp = http_requests.post('https://openapi.ctrader.com/apps/token', data={
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri,
        'client_id': client_id,
        'client_secret': client_secret
    })
    logger.info(f"cTrader token válasz [{resp.status_code}]: {resp.text}")
    resp.raise_for_status()
    tokens = resp.json()
    # A cTrader camelCase (accessToken) VAGY snake_case (access_token) kulcsot is adhat
    access_token = tokens.get('accessToken') or tokens.get('access_token')
    refresh_token = tokens.get('refreshToken') or tokens.get('refresh_token')
    if not access_token:
        raise ValueError(f"cTrader hibaválasz (nincs access token): {tokens}")
    logger.info("✅ cTrader access token kapva")

    # Account ID lekérése
    account_id = os.getenv('CTRADER_ACCOUNT_ID', '')
    try:
        acc_resp = http_requests.get('https://openapi.ctrader.com/apps/accounts',
                                     headers={'Authorization': f'Bearer {access_token}'})
        acc_resp.raise_for_status()
        acc_json = acc_resp.json()
        # A cTrader a listát {"data": [...]} alá csomagolhatja
        accounts = acc_json.get('data', acc_json) if isinstance(acc_json, dict) else acc_json
        if accounts:
            for acc in accounts:
                if not acc.get('live', True):
                    account_id = str(acc.get('accountId') or acc.get('ctidTraderAccountId'))
                    break
            if not account_id:
                first = accounts[0]
                account_id = str(first.get('accountId') or first.get('ctidTraderAccountId'))
    except Exception as e:
        logger.warning(f"Account lekérés sikertelen, manuális ID-t használ: {e}")

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
    return credentials


@app.route('/callback')
def oauth_callback():
    """cTrader OAuth callback – Replit domain-re érkező redirect kezelése"""
    code = request.args.get('code')
    if not code:
        return "Hiányzó authorization code", 400
    try:
        _exchange_code_for_tokens(code, redirect_uri=_get_redirect_uri())
        return """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Sikeres!</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:linear-gradient(135deg,#11998e,#38ef7d);display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}
.box{background:#fff;border-radius:20px;padding:50px;max-width:480px;width:100%;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,.3)}
h1{color:#11998e;margin-bottom:16px}p{color:#666;line-height:1.6;margin-bottom:16px}
.btn{display:inline-block;background:#11998e;color:#fff;padding:12px 32px;border-radius:50px;text-decoration:none;font-weight:700}
</style></head>
<body><div class="box">
<div style="font-size:72px;margin-bottom:16px">✅</div>
<h1>Sikeres Csatlakozás!</h1>
<p>A cTrader fiókod össze lett kapcsolva.<br><code>credentials.json</code> elmentve.</p>
<a href="/" class="btn">⬅️ Vissza a Dashboardra</a>
</div></body></html>"""
    except Exception as e:
        logger.error(f"OAuth callback hiba: {e}")
        return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Hiba</title>
<style>body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;background:#fee;margin:0}}
.box{{background:#fff;padding:40px;border-radius:16px;max-width:480px;text-align:center}}
h1{{color:#e74c3c}}p{{color:#666;margin:12px 0}}
.btn{{display:inline-block;background:#e74c3c;color:#fff;padding:10px 24px;border-radius:50px;text-decoration:none;font-weight:700}}</style></head>
<body><div class="box"><div style="font-size:60px">❌</div>
<h1>Token csere sikertelen</h1><p>{str(e)}</p>
<a href="/oauth-setup" class="btn">↩ Próbáld újra</a></div></body></html>""", 500


@app.route('/oauth-setup')
def oauth_setup():
    """cTrader OAuth beállítás oldal"""
    client_id = os.getenv('CTRADER_CLIENT_ID', '')
    redirect_uri = _get_redirect_uri()
    auth_url = (
        f"https://id.ctrader.com/my/settings/openapi/grantingaccess/"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=trading"
    )
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>cTrader OAuth Setup</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:linear-gradient(135deg,#667eea,#764ba2);min-height:100vh;padding:30px 16px;display:flex;justify-content:center;align-items:flex-start}}
.box{{background:#fff;border-radius:20px;padding:40px;max-width:620px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,.3)}}
h1{{color:#333;margin-bottom:8px;font-size:24px}}
.sub{{color:#666;margin-bottom:28px;font-size:15px}}
.step{{display:flex;gap:14px;margin-bottom:20px;align-items:flex-start}}
.num{{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;border-radius:50%;width:32px;height:32px;display:flex;align-items:center;justify-content:center;font-weight:700;flex-shrink:0;font-size:15px}}
.step-body{{flex:1}}
.step-body strong{{display:block;color:#333;margin-bottom:4px}}
.step-body p{{color:#666;font-size:14px;line-height:1.5}}
.btn{{display:inline-block;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;padding:12px 28px;border-radius:50px;text-decoration:none;font-weight:700;font-size:15px;margin-top:8px}}
.code-box{{background:#f0f0f0;border-radius:8px;padding:10px 14px;font-family:monospace;font-size:12px;word-break:break-all;margin-top:6px;color:#333}}
.divider{{border:none;border-top:1px solid #eee;margin:24px 0}}
form input{{width:100%;padding:12px;border:2px solid #ddd;border-radius:8px;font-size:15px;margin-top:8px;outline:none}}
form input:focus{{border-color:#667eea}}
.submit-btn{{background:linear-gradient(135deg,#11998e,#38ef7d);color:#fff;border:none;padding:12px 28px;border-radius:50px;font-weight:700;font-size:15px;cursor:pointer;margin-top:12px;width:100%}}
.warn{{background:#fff8e1;border-left:4px solid #f9a825;padding:12px;border-radius:5px;font-size:13px;color:#555;margin-top:8px}}
</style></head>
<body><div class="box">
<h1>🔐 cTrader Azonosítás</h1>
<p class="sub">Kövesd az alábbi lépéseket a fiókod csatlakoztatásához.</p>

<div class="step">
  <div class="num">1</div>
  <div class="step-body">
    <strong>Regisztráld ezt az URI-t a Spotware panelen</strong>
    <p>Menj a <a href="https://openapi.ctrader.com/" target="_blank">openapi.ctrader.com</a> oldalra → alkalmazásod → Redirect URIs → add hozzá <em>pontosan</em> ezt:</p>
    <div class="code-box">{redirect_uri}</div>
  </div>
</div>

<div class="step">
  <div class="num">2</div>
  <div class="step-body">
    <strong>Nyisd meg az engedélyező oldalt</strong>
    <p>Kattints a gombra — a cTrader megkérdezi, engedélyezed-e a hozzáférést.</p>
    <a href="{auth_url}" target="_blank" class="btn">🚀 Engedélyezés megnyitása</a>
  </div>
</div>

<div class="step">
  <div class="num">3</div>
  <div class="step-body">
    <strong>Engedélyezés után</strong>
    <p>A cTrader visszairányít ide: <code>{redirect_uri}</code>. Ha automatikusan a Dashboardra jutsz, kész vagy — nincs több teendő. Ha viszont egy kódot látsz az URL-ben, másold ki:</p>
    <div class="code-box">{redirect_uri}?<strong>code=ABC123...</strong></div>
    <div class="warn">📋 Másold ki csak a <strong>code=</strong> utáni részt (pl. <code>ABC123...</code>)</div>
  </div>
</div>

<hr class="divider">

<div class="step">
  <div class="num">4</div>
  <div class="step-body">
    <strong>Illeszd be ide a kódot</strong>
    <form action="/oauth-token" method="POST">
      <input type="text" name="code" placeholder="Másold ide a code értékét..." required autocomplete="off">
      <button type="submit" class="submit-btn">✅ Token lekérése és mentése</button>
    </form>
  </div>
</div>

</div></body></html>"""


@app.route('/oauth-token', methods=['POST'])
def oauth_token():
    """Manuálisan beillesztett authorization code feldolgozása"""
    code = request.form.get('code', '').strip()
    if not code:
        return redirect('/oauth-setup')
    try:
        _exchange_code_for_tokens(code)
        return """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Sikeres!</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:linear-gradient(135deg,#11998e,#38ef7d);display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}
.box{background:#fff;border-radius:20px;padding:50px;max-width:480px;width:100%;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,.3)}
h1{color:#11998e;margin-bottom:16px}p{color:#666;line-height:1.6;margin-bottom:16px}
.btn{display:inline-block;background:#11998e;color:#fff;padding:12px 32px;border-radius:50px;text-decoration:none;font-weight:700}
</style></head>
<body><div class="box">
<div style="font-size:72px;margin-bottom:16px">✅</div>
<h1>Sikeres Csatlakozás!</h1>
<p>A cTrader fiókod össze lett kapcsolva.<br><code>credentials.json</code> elmentve.</p>
<a href="/" class="btn">⬅️ Vissza a Dashboardra</a>
</div></body></html>"""
    except Exception as e:
        logger.error(f"OAuth token hiba: {e}")
        return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Hiba</title>
<style>body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;background:#fee}}
.box{{background:#fff;padding:40px;border-radius:16px;max-width:480px;text-align:center}}h1{{color:#e74c3c}}p{{color:#666;margin:12px 0}}
.btn{{display:inline-block;background:#e74c3c;color:#fff;padding:10px 24px;border-radius:50px;text-decoration:none;font-weight:700}}</style></head>
<body><div class="box"><div style="font-size:60px">❌</div>
<h1>Token csere sikertelen</h1>
<p>{str(e)}</p>
<p>Ellenőrizd, hogy a kódot helyesen másoltad-e be, és hogy az URI be van-e jegyezve a Spotware panelen.</p>
<a href="/oauth-setup" class="btn">↩ Vissza</a></div></body></html>"""


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
