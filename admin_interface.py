#!/usr/bin/env python3
"""
AI Trading Advisor - Admin Interface
Web-alapú adminisztrációs felület a trading bot kezeléséhez
"""

import os
import json
import math
import time
import asyncio
import threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_cors import CORS
from dotenv import load_dotenv
import logging
import requests as http_requests

# Saját modulok
from ai_trading_advisor import AITradingAdvisor
from mcp_server import CTraderMCPServer
from mcp_connection_manager import run_shared

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
            'cycle_interval': os.getenv('TRADING_CYCLE_SECONDS', '60'),
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

            # Mezők frissítése (üres értékeket nem írjuk felül)
            field_map = {
                'ctrader_client_id':     'CTRADER_CLIENT_ID',
                'ctrader_client_secret': 'CTRADER_CLIENT_SECRET',
                'ctrader_account_id':    'CTRADER_ACCOUNT_ID',
                'anthropic_api_key':     'ANTHROPIC_API_KEY',
                'max_positions':         'MAX_OPEN_POSITIONS',
                'risk_per_trade':        'MAX_RISK_PER_TRADE',
                'cycle_interval':        'TRADING_CYCLE_SECONDS',
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

    # Debug módban a Flask reloader a modult kétszer futtatja le (egyszer a
    # figyelő szülőfolyamatban is) - a WERKZEUG_RUN_MAIN csak a tényleges
    # szerver-folyamatban van beállítva, így itt kerüljük el a bot dupla indítását.
    if not debug or os.getenv('WERKZEUG_RUN_MAIN') == 'true':
        _resume_bot_if_needed()

    print(f"""
╔════════════════════════════════════════════╗
║   AI Trading Advisor - Admin Interface    ║
╚════════════════════════════════════════════╝

🌐 Admin felület: http://localhost:{port}
🔧 Debug mód: {debug}

Nyomd meg Ctrl+C a leállításhoz
    """)

    app.run(host='0.0.0.0', port=port, debug=debug)
