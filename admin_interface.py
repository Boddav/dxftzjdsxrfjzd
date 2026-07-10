#!/usr/bin/env python3
"""
AI Trading Advisor - Admin Interface
Web-alapú adminisztrációs felület a trading bot kezeléséhez
"""

import os
import re
import json
import math
import time
import asyncio
import threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from markupsafe import escape
from flask_cors import CORS
from dotenv import load_dotenv
import logging
import requests as http_requests
import uuid
from typing import Optional

# Saját modulok
from ai_trading_advisor import AITradingAdvisor
from ml_predictor import MLPredictor
import backtest_engine
from mcp_server import CTraderMCPServer, resolve_ctrader_account
from mcp_connection_manager import run_shared
import arbitrage_engine

VALID_TIMEFRAMES = {'M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1', 'W1', 'MN1'}
SYMBOL_PATTERN = re.compile(r'^[A-Z0-9._]{2,20}$')

load_dotenv()

# config.json betöltése induláskor (felülírja a .env értékeit ha újabb).
# FONTOS: a CTRADER_CLIENT_ID/CTRADER_CLIENT_SECRET SOHA nem jöhet a
# config.json-ból - kizárólag a Replit Secrets (env) az egyetlen forrás.
# Egy korábbi, config.json-ba mentett elavult Client ID felülírta a helyes
# secretet, és a Client ID/Secret pár összeférhetetlensége miatt a cTrader
# OAuth token-csere "Client credentials invalid" hibával elszállt - ezért
# ezt a két kulcsot itt explicit kizárjuk, még akkor is, ha egy régi
# config.json fájlban esetleg megmaradtak volna.
_CONFIG_JSON_FORBIDDEN_KEYS = {'CTRADER_CLIENT_ID', 'CTRADER_CLIENT_SECRET'}
_config_file = 'config.json'
if os.path.exists(_config_file):
    with open(_config_file, 'r') as _f:
        _loaded_config = json.load(_f)
    _purged_legacy_keys = [k for k in _CONFIG_JSON_FORBIDDEN_KEYS if k in _loaded_config]
    if _purged_legacy_keys:
        for _k in _purged_legacy_keys:
            _loaded_config.pop(_k, None)
        with open(_config_file, 'w') as _f:
            json.dump(_loaded_config, _f, indent=2)
    for _k, _v in _loaded_config.items():
        if _v and _k not in _CONFIG_JSON_FORBIDDEN_KEYS:
            os.environ[_k] = _v

app = Flask(__name__)
app.secret_key = os.getenv('SESSION_SECRET', os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production'))

# CORS engedélyezése - Replit proxy és GitHub Pages
CORS(app, resources={
    r"/api/*": {
        "origins": "*"
    }
})

DEFAULT_SYMBOLS = ['XAUUSD']
AVAILABLE_SYMBOLS = ['XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'BTCUSD']
BOT_STATE_FILE = 'bot_state.json'

# Globális bot instance
bot_instance = None
bot_thread = None
bot_generation = 0  # minden start hívás növeli - elavult szálak nem írhatják felül az új státuszt
bot_lock = threading.Lock()  # start/stop versenyhelyzetek elleni védelem
bot_status = {
    'running': False,
    'last_update': None,
    'positions': [],
    'trades_today': 0,
    'pnl_today': 0.0,
    'symbols': DEFAULT_SYMBOLS
}


def _get_configured_symbols():
    """A kiválasztott kereskedési szimbólumok beolvasása a configból"""
    raw = os.getenv('TRADING_SYMBOLS', '')
    symbols = [s.strip().upper() for s in raw.split(',') if s.strip()]
    return symbols or DEFAULT_SYMBOLS


def _save_bot_state(running, symbols=None):
    """A bot fut/nem-fut állapotának lementése fájlba, hogy szerver-újraindítás
    után automatikusan visszaállítható legyen (lásd _resume_bot_if_needed)."""
    try:
        with open(BOT_STATE_FILE, 'w') as f:
            json.dump({'running': running, 'symbols': symbols or []}, f)
    except OSError as e:
        logger.error(f"Bot állapot mentési hiba: {e}")


def _load_bot_state():
    if not os.path.exists(BOT_STATE_FILE):
        return {'running': False, 'symbols': []}
    try:
        with open(BOT_STATE_FILE, 'r') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"Bot állapot betöltési hiba: {e}")
        return {'running': False, 'symbols': []}


def _bot_thread_target(advisor, generation):
    """A trading bot async loop-jának futtatása egy dedikált szálon"""
    error_message = None
    try:
        asyncio.run(advisor.start())
    except Exception as e:
        error_message = str(e)
        logger.error(f"Bot szál hiba: {e}")
    finally:
        with bot_lock:
            # Csak akkor írjuk felül a globális státuszt, ha még ez a legutóbb indított bot
            if generation == bot_generation:
                bot_status['running'] = False
                bot_status['last_update'] = datetime.now().isoformat()
                if error_message:
                    bot_status['error'] = error_message
                # A bot váratlanul (hibával vagy magától) leállt - a mentett
                # állapotot is frissítjük, különben legközelebbi induláskor
                # feleslegesen (vagy tévesen) próbálná visszaindítani.
                _save_bot_state(running=False)

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


def _get_today_trade_stats():
    """A trade_history.json alapján a MAI (szerver lokális dátum szerinti)
    nyitott kereskedések száma és a mai napon realizált (zárt) P&L összege.

    Megjegyzés: a 'pnl' mező a trade_history bejegyzésekben csak zárási
    eseményeknél van kitöltve, és a zárás-kérés pillanata előtti unrealized
    P&L-ből származik (lásd _record_trade_history hívási helyek
    kommentjeit ai_trading_advisor.py-ban) - kis csúszástól eltekintve jó
    közelítés, de nem 100%-ban a bróker által realizált végleges összeg."""
    trades_today = 0
    pnl_today = 0.0
    today = datetime.now().date()
    try:
        if os.path.exists('trade_history.json'):
            with open('trade_history.json', 'r') as f:
                history = json.load(f)
            for entry in history:
                ts = entry.get('timestamp')
                if not ts:
                    continue
                try:
                    entry_date = datetime.fromisoformat(ts).date()
                except ValueError:
                    continue
                if entry_date != today:
                    continue
                # A siker-státuszok (lásd mcp_server.py EXECUTION_STATUS_LABELS /
                # _record_trade_history hívási helyek): 'accepted', 'filled',
                # 'partial_fill' mind tényleges (ténylegesen leadott/nyitott)
                # kereskedést jelent - a "AI által zárva" és "elutasítva: ..."
                # státuszokat NEM számoljuk új kereskedésként.
                if entry.get('action') in ('accepted', 'filled', 'partial_fill'):
                    trades_today += 1
                pnl = entry.get('pnl')
                if pnl is not None:
                    pnl_today += pnl
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"Mai kereskedési statisztika számítási hiba: {e}")
    return trades_today, round(pnl_today, 2)


@app.route('/api/status')
def api_status():
    """
    Bot státusz API endpoint.

    A bot_status dict-ben tárolt 'positions'/'pnl_today'/'trades_today'
    sosem frissült (csak indításkor íródott, üresen/0-ra) - ezért a felső
    "Aktív Pozíciók" és "Mai P&L" kártyák mindig 0-t mutattak, míg az alsó
    táblázat (amit az /api/positions külön, valós lekéréssel tölt fel)
    helyesen jelent meg. Itt a valós, élő pozíciókból számoljuk a nyitott
    pozíciók darabszámát, és a trade_history.json-ból a MAI, tényleges
    (nyitott/zárt) kereskedésekre vonatkozó számokat.
    """
    status = dict(bot_status)
    open_positions = []
    try:
        if os.path.exists('credentials.json'):
            open_positions = _get_real_positions_cached()
            status['positions'] = open_positions
            status['open_positions_count'] = len(open_positions)
        else:
            open_positions = status.get('positions') or []
            status['open_positions_count'] = len(open_positions)
    except Exception as e:
        logger.error(f"Státusz - pozíciók lekérési hiba: {e}")
        open_positions = status.get('positions') or []
        status['open_positions_count'] = len(open_positions)

    trades_today, realized_pnl_today = _get_today_trade_stats()
    status['trades_today'] = trades_today
    # A dashboard "Nyitott P&L" kártyája a JELENLEG nyitott pozíciók élő,
    # nem realizált P&L összegét mutatja (nem a mai realizált eredményt -
    # arra külön 'realized_pnl_today' mező szolgál, ha később kell egy
    # "Mai realizált P&L" kártya is).
    status['pnl_today'] = round(sum(p.get('pnl', 0) or 0 for p in open_positions), 2)
    status['realized_pnl_today'] = realized_pnl_today
    return jsonify(status)


def _start_bot_internal(persist_state=True, symbols=None):
    """A bot indítási logikájának magja - ezt hívja a /api/start route és az
    induláskori automatikus visszaállítás (_resume_bot_if_needed) is.
    A bot_lock-ot a hívónak kell tartania.
    Ha symbols nincs megadva, a jelenlegi configból olvassuk (ez a normál
    manuális indítás esete); a resume path viszont a legutóbb mentett
    listát adja át, hogy pontosan azt a szimbólumkört induljon újra."""
    global bot_instance, bot_thread, bot_status, bot_generation

    if bot_status['running']:
        return {'success': False, 'message': 'Bot már fut!'}

    # Ellenőrzés: van-e minden szükséges konfiguráció
    anthropic_key = os.getenv('ANTHROPIC_API_KEY')
    if not anthropic_key:
        return {'success': False, 'message': 'ANTHROPIC_API_KEY nincs beállítva!'}

    if not os.getenv('CTRADER_CLIENT_ID'):
        return {'success': False, 'message': 'cTrader credentials nincsenek beállítva! Később add hozzá.'}

    symbols = symbols or _get_configured_symbols()

    bot_generation += 1
    generation = bot_generation
    bot_instance = AITradingAdvisor(anthropic_key, symbols=symbols)
    bot_thread = threading.Thread(target=_bot_thread_target, args=(bot_instance, generation), daemon=True)
    bot_thread.start()

    bot_status['running'] = True
    bot_status['symbols'] = symbols
    bot_status['last_update'] = datetime.now().isoformat()
    bot_status.pop('error', None)

    if persist_state:
        _save_bot_state(running=True, symbols=symbols)

    logger.info(f"Trading bot elindítva - Szimbólumok: {', '.join(symbols)}")
    return {
        'success': True,
        'message': f'Bot elindult, percenként elemzi: {", ".join(symbols)}'
    }


@app.route('/api/start', methods=['POST'])
def api_start_bot():
    """Bot indítása - valódi automatikus kereskedési loop háttérszálon"""
    with bot_lock:
        try:
            result = _start_bot_internal()
            return jsonify(result)
        except Exception as e:
            logger.error(f"Bot indítási hiba: {str(e)}")
            return jsonify({'success': False, 'message': f'Hiba: {str(e)}'})


@app.route('/api/stop', methods=['POST'])
def api_stop_bot():
    """Bot leállítása"""
    global bot_instance, bot_thread, bot_status

    with bot_lock:
        try:
            if not bot_status['running']:
                return jsonify({'success': False, 'message': 'Bot nem fut!'})

            if bot_instance:
                # Jelezzük a loop-nak, hogy álljon le (max. ~5 mp alatt reagál)
                bot_instance.running = False

            thread_to_join = bot_thread

        except Exception as e:
            logger.error(f"Bot leállítási hiba: {str(e)}")
            return jsonify({'success': False, 'message': f'Hiba: {str(e)}'})

    # A join-t a lock-on kívül végezzük, hogy ne blokkoljuk a /api/status-t eközben
    # Az időkorlát a leghosszabb belső hálózati timeoutnál (20s _send_request) nagyobb kell legyen
    if thread_to_join:
        thread_to_join.join(timeout=30)

    with bot_lock:
        if thread_to_join and thread_to_join.is_alive():
            # A szál nem állt le időben - ne töröljük a referenciákat, jelezzük a hibát
            logger.error("Bot leállítási időtúllépés - a szál még fut")
            return jsonify({'success': False, 'message': 'A bot nem állt le időben, próbáld újra.'})

        bot_instance = None
        bot_thread = None
        bot_status['running'] = False
        bot_status['last_update'] = datetime.now().isoformat()
        _save_bot_state(running=False)

    logger.info("Trading bot leállítva")
    return jsonify({'success': True, 'message': 'Bot sikeresen leállítva'})


def _resume_bot_if_needed():
    """Ha a szerver leállás/újraindítás előtt a bot futott, automatikusan
    visszaindítjuk induláskor - lásd _save_bot_state / _load_bot_state.
    Bármilyen hiba itt logolva legyen, de sose akadályozza meg a szerver
    elindulását."""
    try:
        state = _load_bot_state()
        if not state.get('running'):
            return
        saved_symbols = state.get('symbols') or None
        with bot_lock:
            result = _start_bot_internal(symbols=saved_symbols)
        if result.get('success'):
            logger.info("🔄 Bot automatikusan visszaindítva (korábban futott a szerver újraindítása előtt)")
        else:
            logger.warning(f"Bot automatikus visszaindítása sikertelen: {result.get('message')}")
            _save_bot_state(running=False)
    except Exception as e:
        logger.error(f"Bot automatikus visszaindítási hiba: {e}")
        _save_bot_state(running=False)


def _run_async(coro):
    """Segédfüggvény async coroutine futtatásához szinkron Flask route-ban"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


_positions_cache = {'ts': 0.0, 'data': None}
_POSITIONS_CACHE_TTL = 3.0  # mp - lásd lent, miért kell
_positions_cache_lock = threading.Lock()

# A bróker teljes (élő) szimbólumlistájának rövid cache-e - a Beállítások
# oldal ezt tölti be a statikus AVAILABLE_SYMBOLS helyett/mellett. Hosszabb
# TTL, mert a bróker szimbólumkínálata gyakorlatilag sosem változik oldal-
# betöltések között, és nem akarjuk feleslegesen terhelni a megosztott
# kapcsolatot minden Beállítások-oldal megnyitásnál.
_symbols_cache = {'ts': 0.0, 'data': None}
_SYMBOLS_CACHE_TTL = 300.0  # mp
_symbols_cache_lock = threading.Lock()


def _get_available_symbols_cached():
    """
    A cTrader bróker teljes, élő szimbólumlistájának neveit adja vissza
    (rövid cache mögött). Ha nincs azonosítás vagy hiba történik, None-t ad
    vissza - a hívó ilyenkor essen vissza a statikus AVAILABLE_SYMBOLS-ra.
    """
    if not os.path.exists('credentials.json'):
        return None
    with _symbols_cache_lock:
        now = time.monotonic()
        if _symbols_cache['data'] is not None and (now - _symbols_cache['ts']) < _SYMBOLS_CACHE_TTL:
            return _symbols_cache['data']
        try:
            async def _fetch(server):
                return await server.get_symbols_list()

            symbols = run_shared(_fetch)
            names = sorted({
                s.get('symbolName') for s in symbols if s.get('symbolName')
            })
            _symbols_cache['data'] = names
            _symbols_cache['ts'] = time.monotonic()
            return names
        except Exception as e:
            logger.warning(f"⚠️ Élő szimbólumlista lekérési hiba, statikus lista lesz használva: {e}")
            return None


async def _fetch_real_positions(server):
    await server.get_symbols_list()  # symbolId -> symbolName cache feltöltése
    raw_positions = await server.get_positions()

    id_to_name = {s.get('symbolId'): name for name, s in server.symbols_cache.items()}

    # Élő ár lekérése minden nyitott pozíció szimbólumához - ez KIZÁRÓLAG a
    # currentPrice megjelenítéséhez kell, nem a P&L számításához. A P&L-t
    # korábban itt magunk számoltuk (árfolyam-különbség * contract size *
    # lot), ami két hibát is okozott: (1) a quote-deviza -> számla-deviza
    # átváltást (pl. USDJPY: JPY -> USD) magunknak kellett leprogramozni,
    # ami könnyen elromlik; (2) ez csak egy közelítés a valós bróker
    # P&L-hez képest. Ehelyett most a cTrader szerver saját
    # get_positions_unrealized_pnl()-jét kérdezzük le, ami már a számla
    # devizanemében (USD) adja vissza a pontos, valós P&L-t - ugyanazt,
    # amit a cTrader alkalmazás is mutat.
    unique_symbols = {
        id_to_name.get(p.get('symbol_id')) for p in raw_positions
        if id_to_name.get(p.get('symbol_id'))
    }
    market_data_by_symbol = {}
    for sym in unique_symbols:
        try:
            market_data_by_symbol[sym] = await server.get_market_data(sym)
        except Exception as e:
            logger.warning(f"⚠️ Élő árfolyam lekérési hiba ({sym}): {e}")

    try:
        unrealized_pnl_by_position = await server.get_positions_unrealized_pnl()
    except Exception as e:
        logger.warning(f"⚠️ Szerver-oldali unrealized P&L lekérési hiba: {e}")
        unrealized_pnl_by_position = {}

    positions = []
    for p in raw_positions:
        symbol_id = p.get('symbol_id')
        symbol_name = id_to_name.get(symbol_id, f"ID:{symbol_id}")
        position_id = p.get('position_id')
        entry_price = p.get('entry_price') or 0
        lots = round((p.get('volume') or 0) / 10_000_000, 2)
        side = p.get('side')
        swap = p.get('swap') or 0
        commission = p.get('commission') or 0

        market_data = market_data_by_symbol.get(symbol_name) or {}
        bid = market_data.get('bid')
        ask = market_data.get('ask')

        if bid and ask:
            # Egy nyitott pozíciót a másik irányba lehet zárni: a BUY-t a
            # bid-en, a SELL-t az ask-on - ez adja a valós, aktuálisan
            # realizálható árat.
            current_price = bid if side == 'BUY' else ask
        else:
            # Nincs élő ár (pl. subscription timeout) - visszaesünk a nyitási
            # árra a megjelenítéshez.
            current_price = entry_price

        server_pnl = unrealized_pnl_by_position.get(position_id)
        if server_pnl is not None:
            pnl = round(server_pnl['net'], 2)
        else:
            # Ha a szerver-oldali lekérés kimaradt (pl. átmeneti hálózati
            # hiba), csak a biztosan ismert swap+commission-t mutatjuk -
            # inkább hiányos, mint egy csendben rosszul becsült érték.
            logger.warning(
                f"⚠️ {symbol_name} (id={position_id}): nincs szerver-oldali "
                f"unrealized P&L, csak swap/commission jelenik meg"
            )
            pnl = round(-swap - commission, 2)

        positions.append({
            'id': position_id,
            'symbol': symbol_name,
            'type': side,
            'volume': lots,
            'openPrice': entry_price,
            'currentPrice': current_price,
            'pnl': pnl,
            'openTime': p.get('timestamp')
        })
    return positions


def _get_real_positions_cached():
    """
    Rövid (3s) TTL cache a valós pozíciók köré.

    A dashboard 15s-enként külön hívja az /api/status-t és az /api/positions-t
    - mindkettő ugyanazt a (viszonylag drága, szimbólumonkénti élő
    árfolyamot is lekérő) _fetch_real_positions-t futtatná, egymás után,
    duplán terhelve a megosztott cTrader kapcsolatot (és a run_shared lock
    miatt egymásra is várva). A rövid cache-eléssel a két, egy időben
    érkező kérés valójában egyetlen valós lekérést eredményez.
    """
    with _positions_cache_lock:
        now = time.monotonic()
        if _positions_cache['data'] is not None and (now - _positions_cache['ts']) < _POSITIONS_CACHE_TTL:
            return _positions_cache['data']
        # A lock birtokában futtatjuk a valós lekérést is (nem csak a
        # cache-ellenőrzést) - így két egyidejű kérés nem tud egyszerre
        # "cache-t elszalasztani" és mindkettő valós fetch-et indítani; a
        # második kérés megvárja az elsőt, majd a most frissült cache-t
        # kapja, nem egy második, felesleges valós hívást indít.
        # Az időbélyeget a sikeres fetch UTÁN írjuk, hogy a teljes 3s TTL
        # a lekérés befejezésétől számítson, ne a megkezdésétől.
        positions = run_shared(_fetch_real_positions)
        _positions_cache['data'] = positions
        _positions_cache['ts'] = time.monotonic()
        return positions


@app.route('/api/positions')
def api_positions():
    """Aktuális pozíciók lekérése a valós cTrader demo számláról"""
    try:
        if not os.path.exists('credentials.json'):
            return jsonify({'success': False, 'message': 'Nincs cTrader azonosítás (lásd Azonosítás gomb)'})
        positions = _get_real_positions_cached()
        return jsonify({'success': True, 'positions': positions})
    except Exception as e:
        logger.error(f"Pozíciók lekérési hiba: {e}")
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/test-position', methods=['POST'])
def api_test_position():
    """Valós teszt megbízás küldése a cTrader demo számlára"""
    try:
        if not os.path.exists('credentials.json'):
            return jsonify({'success': False, 'message': 'Előbb végezd el az Azonosítást (OAuth)'})

        data = request.json or {}
        symbol = data.get('symbol', 'EURUSD')
        side = data.get('side', 'BUY')
        lots = float(data.get('lots', 0.01))

        async def _place(server):
            return await server.place_order(symbol=symbol, side=side, lots=lots)

        result = run_shared(_place)

        if result.get('success'):
            logger.info(f"Teszt megbízás elküldve a demo számlára: {symbol} {side} {lots} lot")
            return jsonify({'success': True, 'result': result})
        else:
            return jsonify({'success': False, 'message': result.get('error', 'Ismeretlen hiba')})

    except Exception as e:
        logger.error(f"Teszt megbízás hiba: {e}")
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


@app.route('/api/ai-decisions')
def api_ai_decisions():
    """AI visszajelzési panel - minden AI döntés (HOLD is), nem csak a
    ténylegesen végrehajtott megbízások (lásd /api/history)"""
    try:
        decisions_file = 'ai_decisions.json'
        if os.path.exists(decisions_file):
            with open(decisions_file, 'r') as f:
                decisions = json.load(f)
            return jsonify({'success': True, 'decisions': decisions})
        else:
            return jsonify({'success': True, 'decisions': []})
    except (OSError, json.JSONDecodeError) as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/config')
def config_page():
    """Beállítások oldal"""
    return render_template('config.html')


@app.route('/api/symbols')
def api_symbols():
    """
    A bróker teljes, élő szimbólumlistája a Beállítások oldal kereshető
    választójához. Ha nincs azonosítás vagy a lekérés hibázik, a statikus
    AVAILABLE_SYMBOLS-t adjuk vissza tartalékként (source='static').
    """
    live = _get_available_symbols_cached()
    if live:
        return jsonify({'success': True, 'symbols': live, 'source': 'live'})
    return jsonify({
        'success': True,
        'symbols': AVAILABLE_SYMBOLS,
        'source': 'static',
        'message': 'Nincs élő cTrader kapcsolat - a szűkített alapértelmezett lista jelenik meg.'
    })


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
            'risk_per_trade': os.getenv('MAX_RISK_PER_TRADE', '0.02'),
            'leverage': os.getenv('CTRADER_LEVERAGE', '100'),
            'cycle_interval': os.getenv('TRADING_CYCLE_SECONDS', '60'),
            'symbol_delay': os.getenv('TRADING_SYMBOL_DELAY_SECONDS', '15'),
            'available_symbols': AVAILABLE_SYMBOLS,
            'trading_symbols': _get_configured_symbols()
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
            # A CTRADER_CLIENT_ID/SECRET SOHA nem kerülhet a config.json-ba -
            # kizárólag a Replit Secrets az egyetlen forrás (lásd a fájl elején
            # a startup betöltésnél lévő magyarázatot). Egy esetlegesen még itt
            # maradt régi bejegyzést is töröljük, mielőtt visszaírnánk a fájlt.
            for _forbidden in _CONFIG_JSON_FORBIDDEN_KEYS:
                saved.pop(_forbidden, None)

            # Mezők frissítése (üres értékeket nem írjuk felül)
            field_map = {
                'ctrader_account_id':    'CTRADER_ACCOUNT_ID',
                'anthropic_api_key':     'ANTHROPIC_API_KEY',
                'max_positions':         'MAX_OPEN_POSITIONS',
                'risk_per_trade':        'MAX_RISK_PER_TRADE',
                'leverage':              'CTRADER_LEVERAGE',
                'cycle_interval':        'TRADING_CYCLE_SECONDS',
                'symbol_delay':          'TRADING_SYMBOL_DELAY_SECONDS',
            }
            for form_key, env_key in field_map.items():
                raw_val = data.get(form_key, '')
                # A JSON payload elméletileg bármit tartalmazhat (szám, lista,
                # objektum) egy elvártan string mezőben - .strip() ezeken
                # elszállna egy nem egyértelmű 500-as hibával a válaszul várt
                # explicit 400 helyett, ezért csak str/int/float-ot fogadunk el.
                if isinstance(raw_val, (int, float)):
                    val = str(raw_val).strip()
                elif isinstance(raw_val, str):
                    val = raw_val.strip()
                else:
                    return jsonify({'success': False, 'message': f'Érvénytelen érték a(z) {form_key} mezőhöz.'}), 400
                if val:
                    if env_key == 'CTRADER_ACCOUNT_ID':
                        # A felhasználó könnyen a bróker-specifikus 'traderLogin'
                        # (emberi bejelentkezési szám, pl. 9007309) számot írhatja
                        # be, nem a cTrader Open API által elvárt ctidTraderAccountId-t
                        # (pl. 44533070) - ez korábban CH_CTID_TRADER_ACCOUNT_NOT_FOUND
                        # hibával némán megakadályozta a bot indulását. Ha van
                        # mentett credentials.json-unk, a beírt számot a valódi
                        # accountId-ra fordítjuk (traderLogin vagy ctidTraderAccountId
                        # egyaránt elfogadott bemenetként).
                        try:
                            resolved_id, resolved_live = resolve_ctrader_account_id_for_input(val)
                            if resolved_id != val:
                                logger.info(
                                    f"ℹ️ Account ID '{val}' (traderLogin) automatikusan "
                                    f"lefordítva ctidTraderAccountId-re: {resolved_id}"
                                )
                            val = resolved_id
                            saved['CTRADER_IS_LIVE'] = resolved_live
                            os.environ['CTRADER_IS_LIVE'] = str(resolved_live)
                        except Exception as e:
                            logger.warning(f"Account ID fordítás sikertelen, eredeti érték marad: {e}")
                    if env_key == 'TRADING_CYCLE_SECONDS':
                        # Alsó és felső korlát, hogy a felhasználó véletlenül
                        # se tudjon olyan gyakori ciklust beállítani, ami
                        # Claude API rate limitbe/túlköltésbe futna (lásd
                        # korábbi Opus incidenst - a ciklusidő közvetlenül
                        # szorozza az API hívások/óra számát, szimbólumonként
                        # eggyel), és math.isfinite kizárja a NaN/inf értékeket,
                        # amiket a float() simán elfogadna, de <30 nem szűrne ki.
                        try:
                            parsed = float(val)
                            if not math.isfinite(parsed) or parsed < 30 or parsed > 3600:
                                return jsonify({'success': False, 'message': 'A ciklusidő 30 és 3600 másodperc között lehet.'}), 400
                        except ValueError:
                            return jsonify({'success': False, 'message': 'Érvénytelen ciklusidő érték.'}), 400
                    if env_key == 'TRADING_SYMBOL_DELAY_SECONDS':
                        try:
                            parsed = float(val)
                            if not math.isfinite(parsed) or parsed < 0 or parsed > 3600:
                                return jsonify({'success': False, 'message': 'A szimbólumok közti szünet 0 és 3600 másodperc között lehet.'}), 400
                        except ValueError:
                            return jsonify({'success': False, 'message': 'Érvénytelen szünet érték.'}), 400
                    saved[env_key] = val
                    os.environ[env_key] = val  # azonnal érvényes a futó processben

            # Kereskedési szimbólumok (lista -> vesszővel elválasztott string)
            symbols = data.get('trading_symbols')
            if isinstance(symbols, list) and symbols:
                symbols_str = ','.join(s.strip().upper() for s in symbols if s.strip())
                saved['TRADING_SYMBOLS'] = symbols_str
                os.environ['TRADING_SYMBOLS'] = symbols_str

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


@app.route('/arbitrage')
def arbitrage_page():
    """Bróker közötti árarbitrázs (demo, kísérleti) oldal"""
    return render_template('arbitrage.html')


@app.route('/analytics')
def analytics_page():
    """ML szignál minőség + Backtesting oldal"""
    return render_template('analytics.html')


@app.route('/api/ml-quality')
def api_ml_quality():
    """
    Élő ML szignál-minőség (a ténylegesen kiadott predikciók utólagos
    kiértékelése), és opcionálisan (ha ?historical=1) egy izolált,
    train/test-alapú historikus kiértékelés is egy adott szimbólumra.
    """
    try:
        # Friss MLPredictor példány - az __init__ a lemezen (ml_quality_log.json)
        # tárolt élő nyomkövetési adatokat tölti be, nem függ attól, fut-e
        # éppen a bot (bot_instance lehet None, ha le van állítva).
        predictor = MLPredictor()
        symbol = request.args.get('symbol') or None
        if symbol:
            symbol = symbol.strip().upper()
            if not SYMBOL_PATTERN.match(symbol):
                return jsonify({'success': False, 'message': 'Érvénytelen szimbólum formátum.'}), 400
        stats = predictor.get_quality_stats(symbol=symbol)

        result = {'success': True, 'live': stats}

        if request.args.get('historical') == '1':
            hist_symbol = symbol or 'XAUUSD'
            timeframe = request.args.get('timeframe', 'M5').strip().upper()
            if timeframe not in VALID_TIMEFRAMES:
                return jsonify({'success': False, 'message': f'Érvénytelen idősík. Választható: {", ".join(sorted(VALID_TIMEFRAMES))}'}), 400
            try:
                count = int(request.args.get('count', 500))
            except ValueError:
                return jsonify({'success': False, 'message': 'Érvénytelen gyertyaszám.'}), 400
            count = min(max(count, 100), 1000)

            async def _fetch(server):
                return await server.get_candles(hist_symbol, timeframe=timeframe, count=count)

            candles = run_shared(_fetch)
            if not candles:
                return jsonify({'success': False, 'message': 'Nem sikerült historikus gyertyát lekérni.'}), 502

            historical = predictor.evaluate_historical(hist_symbol, candles)
            if historical is None:
                return jsonify({'success': False, 'message': 'Túl kevés adat a historikus kiértékeléshez.'}), 400
            result['historical'] = historical

        return jsonify(result)
    except TimeoutError as e:
        return jsonify({'success': False, 'message': str(e)}), 504
    except Exception as e:
        logger.error(f"❌ ML minőség lekérdezési hiba: {e}")
        return jsonify({'success': False, 'message': f'Hiba: {e}'}), 500


_backtest_results_lock = threading.Lock()
BACKTEST_RESULTS_FILE = 'backtest_results.json'


def _load_backtest_results() -> dict:
    if not os.path.exists(BACKTEST_RESULTS_FILE):
        return {}
    try:
        with open(BACKTEST_RESULTS_FILE, 'r') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_backtest_result(symbol: str, result: dict) -> None:
    with _backtest_results_lock:
        all_results = _load_backtest_results()
        all_results[symbol] = result
        tmp_path = f"{BACKTEST_RESULTS_FILE}.tmp-{uuid.uuid4().hex}"
        with open(tmp_path, 'w') as f:
            json.dump(all_results, f, indent=2)
        os.replace(tmp_path, BACKTEST_RESULTS_FILE)


@app.route('/api/backtest/results')
def api_backtest_results():
    """A korábban lefuttatott backtesztek gyorsítótárazott eredményei
    (szimbólumonként az utolsó futás), hogy az oldal újratöltésekor ne
    kelljen azonnal újra lefuttatni."""
    with _backtest_results_lock:
        return jsonify({'success': True, 'results': _load_backtest_results()})


@app.route('/api/backtest/run', methods=['POST'])
def api_backtest_run():
    """
    Backtest lefuttatása egy szimbólumra: historikus gyertyák lekérése
    cTraderből, majd a determinisztikus (technikai szabály + ML szignál)
    stratégia szimulálása - lásd backtest_engine.py a pontos korlátokért
    (nincs Claude, nincs spread/csúszás-szimuláció).
    """
    try:
        data = request.json or {}
        symbol = str(data.get('symbol', '')).strip().upper()
        if not symbol or not SYMBOL_PATTERN.match(symbol):
            return jsonify({'success': False, 'message': 'Érvényes szimbólum megadása kötelező.'}), 400

        timeframe = str(data.get('timeframe', 'M5')).strip().upper()
        if timeframe not in VALID_TIMEFRAMES:
            return jsonify({'success': False, 'message': f'Érvénytelen idősík. Választható: {", ".join(sorted(VALID_TIMEFRAMES))}'}), 400
        try:
            count = int(data.get('candle_count', 500))
            stop_loss_pips = float(data.get('stop_loss_pips', backtest_engine.DEFAULT_STOP_LOSS_PIPS))
            take_profit_pips = float(data.get('take_profit_pips', backtest_engine.DEFAULT_TAKE_PROFIT_PIPS))
            spread_pips = float(data.get('spread_pips', backtest_engine.DEFAULT_SPREAD_PIPS))
            slippage_pips = float(data.get('slippage_pips', backtest_engine.DEFAULT_SLIPPAGE_PIPS))
            min_hold_bars = int(data.get('min_hold_bars', backtest_engine.DEFAULT_MIN_HOLD_BARS))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'Érvénytelen numerikus paraméter.'}), 400

        if not (100 <= count <= 1000):
            return jsonify({'success': False, 'message': 'A gyertyaszám 100 és 1000 között lehet.'}), 400
        if not (5 <= stop_loss_pips <= 500) or not (5 <= take_profit_pips <= 500):
            return jsonify({'success': False, 'message': 'A stop-loss/take-profit 5 és 500 pip között lehet.'}), 400
        if not (0 <= spread_pips <= 50) or not (0 <= slippage_pips <= 50):
            return jsonify({'success': False, 'message': 'A spread/csúszás 0 és 50 pip között lehet.'}), 400
        if not (0 <= min_hold_bars <= 100):
            return jsonify({'success': False, 'message': 'A minimum tartási idő 0 és 100 gyertya között lehet.'}), 400

        async def _fetch(server):
            return await server.get_candles(symbol, timeframe=timeframe, count=count)

        candles = run_shared(_fetch)
        if not candles:
            return jsonify({'success': False, 'message': 'Nem sikerült historikus gyertyát lekérni ehhez a szimbólumhoz.'}), 502

        result = backtest_engine.run_backtest(
            symbol, candles,
            stop_loss_pips=stop_loss_pips,
            take_profit_pips=take_profit_pips,
            spread_pips=spread_pips,
            slippage_pips=slippage_pips,
            min_hold_bars=min_hold_bars,
            timeframe=timeframe,
        )
        _save_backtest_result(symbol, result)
        return jsonify({'success': True, 'result': result})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except TimeoutError as e:
        return jsonify({'success': False, 'message': str(e)}), 504
    except Exception as e:
        logger.error(f"❌ Backtest hiba: {e}")
        return jsonify({'success': False, 'message': f'Hiba: {e}'}), 500


@app.route('/api/arbitrage/status')
def api_arbitrage_status():
    """Élő ár-összehasonlítás, nyitott/lezárt párok és motor-státusz"""
    try:
        return jsonify({'success': True, **arbitrage_engine.engine.get_status_snapshot()})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/arbitrage/brokers', methods=['GET', 'POST'])
def api_arbitrage_brokers():
    """
    GET: bekötött (demo) arbitrázs-brókerek listája (hitelesítő adat nélkül).
    POST: egy meglévő bróker engedélyezése/letiltása ({'name':..., 'enabled': bool}).
    Új bróker hozzáadása NEM itt, hanem a /oauth-setup?broker=<név> OAuth
    folyamaton keresztül történik (lásd oauth_setup) - itt hitelesítő adatot
    sosem fogadunk el nyers JSON-ként.
    """
    if request.method == 'GET':
        return jsonify({'success': True, 'brokers': arbitrage_engine.load_brokers()})

    data = request.json or {}
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'success': False, 'message': 'Hiányzó bróker név'}), 400
    brokers = arbitrage_engine.load_brokers()
    for b in brokers:
        if b.get('name') == name:
            b['enabled'] = bool(data.get('enabled', True))
            arbitrage_engine.save_brokers(brokers)
            return jsonify({'success': True, 'brokers': brokers})
    return jsonify({'success': False, 'message': f'Nincs ilyen bróker: {name}'}), 404


@app.route('/api/arbitrage/brokers/<name>', methods=['DELETE'])
def api_arbitrage_broker_delete(name):
    """Egy arbitrázs-bróker eltávolítása (hitelesítő fájl + lista bejegyzés)"""
    try:
        brokers = [b for b in arbitrage_engine.load_brokers() if b.get('name') != name]
        arbitrage_engine.save_brokers(brokers)
        cred_path = arbitrage_engine.broker_credentials_path(name)
        if os.path.exists(cred_path):
            os.remove(cred_path)
        return jsonify({'success': True, 'brokers': brokers})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/arbitrage/config', methods=['GET', 'POST'])
def api_arbitrage_config():
    """Arbitrázs paraméterek (küszöbök, lot-méret, napi veszteséglimit stb.)"""
    if request.method == 'GET':
        return jsonify({'success': True, 'config': arbitrage_engine.load_config()})

    data = request.json or {}
    try:
        cfg = {}
        if 'symbols' in data:
            symbols = data['symbols']
            if not isinstance(symbols, list) or not symbols:
                return jsonify({'success': False, 'message': 'Legalább egy szimbólumot meg kell adni'}), 400
            cfg['symbols'] = [s.strip().upper() for s in symbols if s.strip()]
        for key in ('open_threshold_pct', 'close_threshold_pct', 'lots', 'daily_loss_limit_usd'):
            if key in data:
                val = float(data[key])
                if not math.isfinite(val) or val < 0:
                    return jsonify({'success': False, 'message': f'Érvénytelen érték: {key}'}), 400
                cfg[key] = val
        if 'safety_timeout_minutes' in data:
            val = float(data['safety_timeout_minutes'])
            if not math.isfinite(val) or val < 1:
                return jsonify({'success': False, 'message': 'A biztonsági időkorlát legalább 1 perc lehet'}), 400
            cfg['safety_timeout_minutes'] = val
        if 'poll_interval_seconds' in data:
            val = float(data['poll_interval_seconds'])
            if not math.isfinite(val) or val < 2:
                return jsonify({'success': False, 'message': 'A frissítési gyakoriság legalább 2 másodperc lehet'}), 400
            cfg['poll_interval_seconds'] = val
        if 'auto_execute' in data:
            cfg['auto_execute'] = bool(data['auto_execute'])

        arbitrage_engine.save_config(cfg)
        return jsonify({'success': True, 'config': arbitrage_engine.load_config()})
    except (TypeError, ValueError) as e:
        return jsonify({'success': False, 'message': f'Érvénytelen érték: {e}'}), 400


@app.route('/api/arbitrage/start', methods=['POST'])
def api_arbitrage_start():
    try:
        arbitrage_engine.engine.start()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/arbitrage/stop', methods=['POST'])
def api_arbitrage_stop():
    try:
        arbitrage_engine.engine.stop()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


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


def _get_redirect_uri():
    """Visszaadja a helyes redirect URI-t (Replit, GitHub Codespaces vagy localhost).

    A callback route az admin felület portján (ADMIN_PORT, alap: 5000) fut.
    """
    port = os.getenv('ADMIN_PORT', '5000')

    # Replit környezet
    replit_domain = os.getenv('REPLIT_DEV_DOMAIN', '')
    if replit_domain:
        return f"https://{replit_domain}/callback"

    # GitHub Codespaces környezet (pl. https://<name>-5000.app.github.dev/callback)
    codespace_name = os.getenv('CODESPACE_NAME', '')
    gh_domain = os.getenv('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN', '')
    if codespace_name and gh_domain:
        return f"https://{codespace_name}-{port}.{gh_domain}/callback"

    # Helyi fejlesztés
    return f"http://localhost:{port}/callback"


def _exchange_code_for_tokens(code, redirect_uri=None, broker_name=None):
    """
    Authorization code cseréje tokenekre. Visszaadja a credentials dict-et vagy dob kivételt.

    Args:
        broker_name: Ha megadott, az eredmény NEM a fő credentials.json-ba
            kerül, hanem az arbitrázs motor számára egy külön, névhez kötött
            fájlba (lásd arbitrage_engine.broker_credentials_path), és a
            bróker bejegyzés az arbitrage_brokers.json listába kerül. Ugyanaz
            a cTrader alkalmazás (CTRADER_CLIENT_ID/SECRET) engedélyezi több,
            különböző demo számla hozzáférését - ez felel meg a "több bróker"
            forgatókönyvnek a cTrader ID egységes bejelentkezésén keresztül.
    """
    client_id = os.getenv('CTRADER_CLIENT_ID', '')
    client_secret = os.getenv('CTRADER_CLIENT_SECRET', '')
    if redirect_uri is None:
        redirect_uri = _get_redirect_uri()

    resp = http_requests.get('https://openapi.ctrader.com/apps/token', params={
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri,
        'client_id': client_id,
        'client_secret': client_secret
    }, headers={'Accept': 'application/json'})
    # FONTOS: a nyers válasz test accessToken/refreshToken-t tartalmaz - ezt
    # SOHA nem logoljuk teljes egészében (naplófájlból kiszivárgó éles
    # kereskedési jogosultságot adó token biztonsági kockázat). Csak a
    # státuszkódot és a hibamezőket (errorCode/description) logoljuk.
    resp.raise_for_status()
    tokens = resp.json()
    logger.info(
        f"cTrader token válasz [{resp.status_code}] errorCode={tokens.get('errorCode')} "
        f"description={tokens.get('description')}"
    )
    # A cTrader camelCase (accessToken) VAGY snake_case (access_token) kulcsot is adhat
    access_token = tokens.get('accessToken') or tokens.get('access_token')
    refresh_token = tokens.get('refreshToken') or tokens.get('refresh_token')
    if not access_token:
        raise ValueError(f"cTrader hibaválasz (nincs access token): errorCode={tokens.get('errorCode')} "
                          f"description={tokens.get('description')}")
    logger.info("✅ cTrader access token kapva")

    # Account ID lekérése a ProtoOAGetAccountListByAccessTokenReq WS üzenettel
    # (lásd mcp_server.resolve_ctrader_account - nincs erre REST végpont).
    # Ha ez sikertelen, NEM esünk vissza némán egy soha nem ellenőrzött,
    # manuálisan beállított CTRADER_ACCOUNT_ID-ra (ez korábban egy hibás
    # traderLogin/ctidTraderAccountId keveredést és fail-closed 'live'
    # feltételezést okozott, ami CH_CTID_TRADER_ACCOUNT_NOT_FOUND hibával
    # némán megakadályozta a bot indulását) - inkább azonnal, explicit
    # hibával elszáll az OAuth folyamat, hogy a felhasználó tudjon róla.
    account_id = os.getenv('CTRADER_ACCOUNT_ID', '')
    try:
        # FONTOS: a cTrader Open API-nak NINCS 'https://openapi.ctrader.com/apps/accounts'
        # REST végpontja (ez korábban mindig 404-et adott, ami miatt ez az ág mindig
        # a kivétel-kezelő fail-closed 'live' ágra esett, és a manuálisan beállított,
        # SOHA nem ellenőrzött account_id-t használta - ez okozta a
        # CH_CTID_TRADER_ACCOUNT_NOT_FOUND hibát induláskor). A számlalistát a
        # ProtoOAGetAccountListByAccessTokenReq WebSocket üzenettel kell lekérni,
        # mind a demo, mind a live hoszton (lásd mcp_server.resolve_ctrader_account).
        account_id, resolved_is_live = asyncio.run(
            resolve_ctrader_account(client_id, client_secret, access_token,
                                     preferred_account_id=account_id or None)
        )
        logger.info(f"✅ cTrader számla feloldva: {account_id} (live={resolved_is_live})")
    except Exception as e:
        # NEM esünk vissza némán a manuális/soha nem ellenőrzött account_id-ra -
        # ez korábban egy hibás (traderLogin, nem ctidTraderAccountId) értéket
        # engedett át a rendszeren, ami csak a bot indításakor, egy nehezen
        # visszakövethető CH_CTID_TRADER_ACCOUNT_NOT_FOUND hibával derült ki.
        # Inkább azonnal, explicit hibával jelezzük a felhasználónak.
        raise ValueError(
            f"Nem sikerült lekérni a cTrader számla adatait (accountId, demo/live) "
            f"a megadott access tokennel: {e}"
        )

    if broker_name and resolved_is_live:
        raise ValueError(
            "A kiválasztott cTrader számla ÉLES (live) számlának tűnik. Az arbitrázs "
            "brókerek kizárólag DEMO számlával köthetők be - válassz demo számlát a "
            "cTrader ID bejelentkezéskor, és próbáld újra."
        )

    credentials = {
        'clientId': client_id,
        'clientSecret': client_secret,
        'accessToken': access_token,
        'refreshToken': refresh_token,
        'accountId': account_id,
        'redirectUri': redirect_uri,
        'isLive': resolved_is_live,
    }

    if broker_name:
        from arbitrage_engine import broker_credentials_path, load_brokers, save_brokers, MAX_BROKERS
        path = broker_credentials_path(broker_name)
        with open(path, 'w') as f:
            json.dump(credentials, f, indent=2)
        brokers = [b for b in load_brokers() if b.get('name') != broker_name]
        if len(brokers) >= MAX_BROKERS:
            raise ValueError(f"Legfeljebb {MAX_BROKERS} bróker köthető be")
        brokers.append({'name': broker_name, 'account_id': account_id, 'enabled': True})
        save_brokers(brokers)
        logger.info(f"💾 Arbitrázs bróker hitelesítve és mentve: {broker_name} ({path})")
    else:
        with open('credentials.json', 'w') as f:
            json.dump(credentials, f, indent=2)
        logger.info("💾 credentials.json létrehozva")
    return credentials


def resolve_ctrader_account_id_for_input(entered_value: str):
    """
    A Beállítások oldalon manuálisan beírt cTrader számlaazonosító
    feloldása a valódi ctidTraderAccountId-ra.

    A felhasználó könnyen a bróker-specifikus 'traderLogin' (emberi
    bejelentkezési szám) értéket írhatja be a cTrader Open API által
    valójában elvárt ctidTraderAccountId helyett - ez korábban némán
    CH_CTID_TRADER_ACCOUNT_NOT_FOUND hibát okozott a bot indításakor.
    Ehhez a meglévő, elmentett credentials.json Client ID/Secret/Access
    Token adatait használjuk a ProtoOAGetAccountListByAccessTokenReq
    lekéréshez (lásd mcp_server.resolve_ctrader_account).

    Ha nincs még mentett credentials.json (első beállítás, OAuth előtt),
    nem tudunk fordítani - ilyenkor az eredeti értéket adjuk vissza
    változatlanul, hibát nem dobunk, mert a bot indítás előtt az
    OAuth folyamat (_exchange_code_for_tokens) mindenképp lefut és ott
    a helyes érték felülíródik.

    Returns:
        (account_id: str, is_live: bool)
    """
    if not os.path.exists('credentials.json'):
        return entered_value, True
    with open('credentials.json', 'r') as f:
        creds = json.load(f)
    return asyncio.run(
        resolve_ctrader_account(
            creds['clientId'], creds['clientSecret'], creds['accessToken'],
            preferred_account_id=entered_value
        )
    )


def _valid_broker_name(name: str) -> bool:
    return bool(name) and all(c.isalnum() or c in ('-', '_') for c in name)


class OAuthStateError(Exception):
    """A state/nonce nem egyezik a sessionben tárolttal - lásd _broker_name_from_state."""


def _broker_name_from_state(state: str) -> Optional[str]:
    """
    A /oauth-setup által kiadott, session-hez kötött nonce-ot ellenőrzi a
    callback 'state' paraméterében.

    Szigorúan elutasítja (OAuthStateError-t dob), ha VOLT folyamatban lévő
    OAuth kérés (van session nonce), de a beérkező state nem egyezik -
    ez korábban csendben a fő (broker_name=None) hitelesítési útvonalra esett
    vissza, ami gyengítette a CSRF/state védelmet. Ha nincs session nonce
    (pl. a felhasználó közvetlenül nyitotta a callback URL-t egy korábbi,
    már felhasznált munkamenetből), a fő fiók azonosítását engedélyezzük
    changetlenül (None-t ad vissza) - ez a visszafelé kompatibilis, nem
    bróker-specifikus OAuth folyamat.
    """
    expected_nonce = session.pop('oauth_nonce', None)
    broker_name = session.pop('oauth_broker', None)
    if expected_nonce is None:
        return None
    if not state or state != expected_nonce:
        raise OAuthStateError("Érvénytelen vagy lejárt OAuth state - próbáld újra a folyamatot elölről.")
    return broker_name if broker_name and _valid_broker_name(broker_name) else None


@app.route('/callback')
def oauth_callback():
    """cTrader OAuth callback – Replit domain-re érkező redirect kezelése"""
    code = request.args.get('code')
    if not code:
        return "Hiányzó authorization code", 400
    try:
        broker_name = _broker_name_from_state(request.args.get('state', ''))
    except OAuthStateError as e:
        logger.error(f"OAuth state ellenőrzési hiba: {e}")
        return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Hiba</title>
<style>body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;background:#fee;margin:0}}
.box{{background:#fff;padding:40px;border-radius:16px;max-width:480px;text-align:center}}
h1{{color:#e74c3c}}p{{color:#666;margin:12px 0}}
.btn{{display:inline-block;background:#e74c3c;color:#fff;padding:10px 24px;border-radius:50px;text-decoration:none;font-weight:700}}</style></head>
<body><div class="box"><div style="font-size:60px">❌</div>
<h1>Érvénytelen kérés</h1><p>{escape(str(e))}</p>
<a href="/oauth-setup" class="btn">↩ Próbáld újra</a></div></body></html>""", 400
    try:
        _exchange_code_for_tokens(code, redirect_uri=_get_redirect_uri(), broker_name=broker_name)
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
    """
    cTrader OAuth beállítás oldal.

    Ha a ?broker=<név> query paraméter megadott, ez egy ÚJ, az arbitrázs
    motorhoz tartozó bróker-fiók (demo) hozzákötése - a state paraméterben
    visszaküldött névvel a callback tudja, hova mentse a hitelesítést (lásd
    _broker_name_from_state / _exchange_code_for_tokens). Query param nélkül
    ez a fő (egy-számlás) fiók azonosítása, változatlan viselkedéssel.
    """
    broker_name = request.args.get('broker', '').strip()
    if broker_name and not _valid_broker_name(broker_name):
        return "Érvénytelen bróker név (csak betű, szám, '-' és '_' engedélyezett)", 400
    client_id = os.getenv('CTRADER_CLIENT_ID', '')
    redirect_uri = _get_redirect_uri()

    # A state paramétert egy, a szerver-oldali sessionben tárolt nonce-hoz
    # kötjük (session['oauth_nonce'] -> broker_name), hogy a callback/
    # oauth-token ne fogadjon el egy tetszőlegesen küldött 'broker' mezőt
    # forrás nélkül - enélkül egy támadó egy másik felhasználó folyamatban
    # lévő OAuth code-jával (vagy sajátjával, de más 'broker' mezővel) egy
    # tetszőleges névre írhatna hitelesítő adatot.
    nonce = uuid.uuid4().hex
    session['oauth_nonce'] = nonce
    session['oauth_broker'] = broker_name or None
    state_param = f"&state={nonce}"
    auth_url = (
        f"https://id.ctrader.com/my/settings/openapi/grantingaccess/"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=trading"
        f"{state_param}"
    )
    broker_hidden_input = (
        f'<input type="hidden" name="broker_nonce" value="{escape(nonce)}">'
    )
    heading = f"🔐 Bróker azonosítás: {escape(broker_name)}" if broker_name else "🔐 cTrader Azonosítás"
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
<h1>{heading}</h1>
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
      {broker_hidden_input}
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
    try:
        broker_name = _broker_name_from_state(request.form.get('broker_nonce', ''))
    except OAuthStateError as e:
        logger.error(f"OAuth state ellenőrzési hiba: {e}")
        return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Hiba</title>
<style>body{{font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh;background:#fee;margin:0}}
.box{{background:#fff;padding:40px;border-radius:16px;max-width:480px;text-align:center}}
h1{{color:#e74c3c}}p{{color:#666;margin:12px 0}}
.btn{{display:inline-block;background:#e74c3c;color:#fff;padding:10px 24px;border-radius:50px;text-decoration:none;font-weight:700}}</style></head>
<body><div class="box"><div style="font-size:60px">❌</div>
<h1>Érvénytelen kérés</h1><p>{escape(str(e))}</p>
<a href="/oauth-setup" class="btn">↩ Próbáld újra</a></div></body></html>""", 400
    if not code:
        return redirect('/oauth-setup')
    try:
        _exchange_code_for_tokens(code, broker_name=broker_name)
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

    # Debug módban a Flask reloader a modult kétszer futtatja le (egyszer a
    # figyelő szülőfolyamatban is) - a WERKZEUG_RUN_MAIN csak a tényleges
    # szerver-folyamatban van beállítva, így itt kerüljük el a bot dupla indítását.
    if not debug or os.getenv('WERKZEUG_RUN_MAIN') == 'true':
        _resume_bot_if_needed()
        arbitrage_engine.engine.resume_if_needed()

    print(f"""
╔════════════════════════════════════════════╗
║   AI Trading Advisor - Admin Interface    ║
╚════════════════════════════════════════════╝

🌐 Admin felület: http://localhost:{port}
🔧 Debug mód: {debug}

Nyomd meg Ctrl+C a leállításhoz
    """)

    app.run(host='0.0.0.0', port=port, debug=debug)
