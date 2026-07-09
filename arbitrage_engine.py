#!/usr/bin/env python3
"""
Több bróker közötti (cTrader) árarbitrázs motor - KIZÁRÓLAG DEMO számlákon.

Ez egy önálló, a fő (Claude-alapú, egy-számlás) trading bottól teljesen
elkülönülő alrendszer. Nem osztja meg a kapcsolatát/állapotát a fő bottal
(mcp_connection_manager.py-vel) - saját, N darab egyidejű CTraderMCPServer
kapcsolatot tart fenn, egyet brókerenként, mindegyiket saját hitelesítéssel.

Működés röviden:
- Konfigurált szimbólumonként, konfigurált gyakorisággal lekéri az árat
  (bid/ask) minden bekötött brókeren.
- Ha két bróker közötti árkülönbség (a drágább BUY-ára vs az olcsóbb
  SELL-ára, a valódi végrehajtási költséget figyelembe véve) eléri a
  konfigurált nyitási küszöböt, ÉS az adott szimbólumon nincs már nyitott
  arbitrázs-pár, egyszerre nyit egy BUY-t az olcsóbb és egy SELL-t a
  drágább brókeren, azonos lot-mérettel.
- Minden nyitott párt figyel: ha az árkülönbség a zárási küszöb alá
  konvergál, VAGY a pár kora eléri a biztonsági időkorlátot, zárja mindkét
  lábat.
- Ha egy pár nyitásakor az egyik láb sikertelen, azonnal visszazárja a
  másik (sikeres) lábat, hogy ne maradjon egyoldalú, fedezetlen kitettség.
- Napi realizált veszteséglimit felett új pár nem nyílik (a meglévők
  kezelése/zárása továbbra is fut).

Biztonsági védőháló: a CTraderMCPServer.place_order/close_position már
maga is elutasítja a végrehajtást, ha a hozzá tartozó credentials
'isLive': true-t jelez - ez az arbitrázs motorra is érvényes, tehát éles
számlán akkor sem tud megbízást adni, ha véletlenül élő hitelesítő adatot
konfigurálnának be.
"""

import asyncio
import copy
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from mcp_server import CTraderMCPServer

logger = logging.getLogger(__name__)

BROKERS_FILE = 'arbitrage_brokers.json'
CONFIG_FILE = 'arbitrage_config.json'
STATE_FILE = 'arbitrage_state.json'
LOG_FILE = 'arbitrage_log.json'
CREDENTIALS_PREFIX = 'credentials_arb_'

MAX_BROKERS = 5

DEFAULT_CONFIG = {
    'symbols': ['EURUSD'],
    'open_threshold_pct': 0.05,     # % árkülönbség a mid-áron, ami felett nyitunk
    'close_threshold_pct': 0.01,    # % árkülönbség, ami alá konvergálva zárunk
    'lots': 0.01,
    'safety_timeout_minutes': 30,   # ha eddig nem konvergál, kényszer-zárás
    'poll_interval_seconds': 5,
    'daily_loss_limit_usd': 20.0,
    'auto_execute': True,           # False = csak jelzés, nem nyit valós pozíciót
}


def _read_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"⚠️ Arbitrázs fájl olvasási hiba ({path}): {e}")
        return default


def _write_json(path: str, data) -> None:
    """Atomikus írás (tmp fájl + rename), hogy egy félbeszakadt írás ne
    hagyjon sérült JSON-t egy másik szál/folyamat számára olvasva."""
    tmp_path = f"{path}.tmp-{uuid.uuid4().hex}"
    with open(tmp_path, 'w') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


def load_brokers() -> List[Dict]:
    """[{'name': str, 'account_id': str, 'enabled': bool}, ...] - a valós
    hitelesítő adatok (client secret, access token) SOSEM ebben a fájlban,
    csak a per-broker credentials_arb_<name>.json-ban."""
    return _read_json(BROKERS_FILE, [])


def save_brokers(brokers: List[Dict]) -> None:
    _write_json(BROKERS_FILE, brokers)


def broker_credentials_path(name: str) -> str:
    safe = "".join(c for c in name if c.isalnum() or c in ('-', '_')).strip()
    if not safe:
        raise ValueError("Érvénytelen bróker név")
    return f"{CREDENTIALS_PREFIX}{safe}.json"


def load_config() -> Dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(_read_json(CONFIG_FILE, {}))
    return cfg


def save_config(cfg: Dict) -> None:
    merged = load_config()
    merged.update(cfg)
    _write_json(CONFIG_FILE, merged)


class ArbitrageEngine:
    """
    Singleton-szerűen használt motor - egy dedikált háttérszálon futó saját
    asyncio event loop-on tartja fenn az összes bróker-kapcsolatot és futtatja
    a folyamatos ár-összehasonlító/végrehajtó ciklust.
    """

    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._servers: Dict[str, CTraderMCPServer] = {}
        self._running = False
        self._stop_event: Optional[asyncio.Event] = None
        # Élettartam-átmenetek (start/stop) kizárólagos zárolása - enélkül egy
        # gyors stop()+start() pár (vagy két egyidejű /api/arbitrage/start
        # hívás) egy még leálló régi szálat és egy új szálat is
        # párhuzamosan futtathatna, mert a régi ciklus a _stop_event/_loop
        # megosztott mezőket olvassa, amiket az új start() felülír, mielőtt
        # a régi szál ténylegesen leállna - ez duplikált/ütköző
        # ár-lekérést és megbízásküldést okozhatna.
        self._lifecycle_lock = threading.Lock()

        # Élő állapot, amit a dashboard olvas (lásd get_status_snapshot)
        self.latest_prices: Dict[str, Dict[str, Dict]] = {}  # symbol -> broker -> {bid, ask, ts}
        self.open_pairs: List[Dict] = []
        self.closed_pairs: List[Dict] = []
        self.last_error: Optional[str] = None
        self._state_lock = threading.Lock()

        self._load_state()

    # --- Állapot perzisztencia -------------------------------------------------

    def _load_state(self):
        state = _read_json(STATE_FILE, {})
        with self._state_lock:
            self.open_pairs = state.get('open_pairs', [])
            self.closed_pairs = _read_json(LOG_FILE, [])[-200:]

    def _save_state(self):
        with self._state_lock:
            _write_json(STATE_FILE, {'open_pairs': list(self.open_pairs)})

    def _append_log(self, entry: Dict):
        with self._state_lock:
            self.closed_pairs.append(entry)
            self.closed_pairs = self.closed_pairs[-200:]
        history = _read_json(LOG_FILE, [])
        history.append(entry)
        _write_json(LOG_FILE, history[-1000:])

    # --- Életciklus --------------------------------------------------------

    def is_running(self) -> bool:
        return self._running

    def start(self):
        """
        Indítás/leállítás kizárólag a _lifecycle_lock birtokában történhet,
        és stop() MEGVÁRJA (join) a régi háttérszál tényleges leállását,
        mielőtt egy új start() új szálat indíthatna - enélkül egy gyors
        stop()+start() pár (vagy két egyidejű /api/arbitrage/start hívás) a
        régi és az új ciklust is párhuzamosan futtathatná (lásd _run_loop
        loop-lokális stop_event-jét), ami duplikált ár-lekérést és
        megbízásküldést okozna.
        """
        with self._lifecycle_lock:
            if self._running:
                return
            brokers = [b for b in load_brokers() if b.get('enabled', True)]
            if len(brokers) < 2:
                raise ValueError("Legalább 2 bekötött (engedélyezett) bróker szükséges az arbitrázs indításához")
            if len(brokers) > MAX_BROKERS:
                raise ValueError(f"Legfeljebb {MAX_BROKERS} bróker támogatott")

            # Ha egy korábbi szál még nem fejeződött be teljesen (pl. egy
            # korábbi stop() még zajlik), megvárjuk, mielőtt újat indítanánk.
            if self._thread is not None and self._thread.is_alive():
                self._thread.join(timeout=10)
                if self._thread.is_alive():
                    raise RuntimeError(
                        "A korábbi arbitrázs motor szál még nem állt le - próbáld újra pár másodperc múlva."
                    )

            self._running = True
            self._thread = threading.Thread(target=self._run_loop, name="arbitrage-engine", daemon=True)
            self._thread.start()
            logger.info(f"🔀 Arbitrázs motor elindult ({len(brokers)} bróker)")

    def stop(self, join_timeout: float = 10):
        """Leállítási jelzés küldése, majd (a lock alatt) megvárja a szál
        tényleges leállását, hogy egy közvetlenül utána hívott start() ne
        indíthasson párhuzamos, második ciklust."""
        with self._lifecycle_lock:
            self._running = False
            loop = self._loop
            stop_event = self._stop_event
            if loop and stop_event:
                try:
                    loop.call_soon_threadsafe(stop_event.set)
                except RuntimeError:
                    pass
            logger.info("⏹ Arbitrázs motor leállítási kérés elküldve")
            thread = self._thread
            if thread is not None and thread.is_alive():
                thread.join(timeout=join_timeout)
                if thread.is_alive():
                    logger.warning("⚠️ Arbitrázs motor szál nem állt le az időkorláton belül")

    def _run_loop(self):
        # Loop-lokális változók - ne csak a megosztott self._loop/self._stop_event
        # mezőkre támaszkodjunk a ciklus feltételében, mert azokat egy
        # időközben induló új start() felülírhatná, amíg ez a szál még fut.
        local_loop = asyncio.new_event_loop()
        self._loop = local_loop
        asyncio.set_event_loop(local_loop)
        local_stop_event = asyncio.Event()
        self._stop_event = local_stop_event
        try:
            local_loop.run_until_complete(self._main(local_stop_event))
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"❌ Arbitrázs motor hiba, leállt: {e}")
        finally:
            local_loop.run_until_complete(self._disconnect_all())
            self._running = False
            local_loop.close()
            # Csak akkor nullázzuk a megosztott referenciákat, ha még mindig
            # ez a (befejeződő) loop/esemény van beállítva - ha egy új
            # start() időközben már felülírta őket, ne nyúljunk hozzá.
            if self._loop is local_loop:
                self._loop = None
            if self._stop_event is local_stop_event:
                self._stop_event = None

    async def _disconnect_all(self):
        for server in self._servers.values():
            try:
                await server.close()
            except Exception:
                pass
        self._servers.clear()

    async def _ensure_connected(self, name: str) -> Optional[CTraderMCPServer]:
        server = self._servers.get(name)
        if server is None:
            server = CTraderMCPServer(credentials_path=broker_credentials_path(name))
            self._servers[name] = server
        if not server.connected or not server.authenticated:
            await server.connect()
            await server.get_symbols_list()
        return server

    async def _main(self, stop_event: asyncio.Event):
        # A loop-lokális stop_event-et paraméterként kapja (nem a megosztott
        # self._stop_event-et olvassa élőben) - így egy időközben induló új
        # start() által felülírt self._stop_event nem szakítja meg idő előtt
        # (vagy hagyja figyelmen kívül) EZT a futó ciklust.
        while self._running and not stop_event.is_set():
            cfg = load_config()
            brokers = [b['name'] for b in load_brokers() if b.get('enabled', True)]
            try:
                await self._cycle(brokers, cfg)
                self.last_error = None
            except Exception as e:
                self.last_error = str(e)
                logger.error(f"❌ Arbitrázs ciklus hiba: {e}")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=max(cfg.get('poll_interval_seconds', 5), 1))
            except asyncio.TimeoutError:
                pass

    # --- Egy ár-figyelő/végrehajtó ciklus -----------------------------------

    async def _cycle(self, broker_names: List[str], cfg: Dict):
        symbols = cfg.get('symbols') or DEFAULT_CONFIG['symbols']

        # 1) Árak lekérése minden bekötött brókeren, minden figyelt szimbólumra.
        for symbol in symbols:
            prices: Dict[str, Dict] = {}
            for name in broker_names:
                try:
                    server = await self._ensure_connected(name)
                    data = await server.get_market_data(symbol)
                    if data.get('bid') and data.get('ask'):
                        prices[name] = {
                            'bid': data['bid'],
                            'ask': data['ask'],
                            'ts': datetime.now(timezone.utc).isoformat(),
                        }
                except Exception as e:
                    logger.warning(f"⚠️ [{symbol}] Ár lekérési hiba ({name}): {e}")
            with self._state_lock:
                self.latest_prices[symbol] = prices

        # 2) Nyitott párok kezelése (zárás konvergencia/timeout esetén) -
        #    EZ ELŐBB fut, mint az új párok nyitása (lásd a fő bot ugyanezen
        #    mintáját: a régi kitettség lezárása ne blokkolja feleslegesen
        #    az újat, illetve elsőbbséget kap a kockázatcsökkentés).
        await self._manage_open_pairs(cfg)

        # 3) Új arbitrázs-lehetőségek észlelése és (ha auto_execute) nyitása.
        daily_realized = self._daily_realized_pnl()
        if not cfg.get('auto_execute', True):
            return
        if daily_realized <= -abs(cfg.get('daily_loss_limit_usd', 20.0)):
            logger.warning(
                f"⛔ Napi veszteséglimit elérve az arbitrázs motoron ({daily_realized:.2f} USD) - "
                "új pár nyitása szüneteltetve."
            )
            return

        for symbol in symbols:
            with self._state_lock:
                prices = dict(self.latest_prices.get(symbol, {}))
                symbol_has_open_pair = any(p['symbol'] == symbol for p in self.open_pairs)
            if len(prices) < 2:
                continue
            if symbol_has_open_pair:
                continue  # egyszerre csak egy nyitott pár szimbólumonként

            best_pair = self._find_best_opportunity(symbol, prices, cfg)
            if best_pair:
                await self._open_pair(symbol, best_pair, cfg)

    def _find_best_opportunity(self, symbol: str, prices: Dict[str, Dict], cfg: Dict) -> Optional[Dict]:
        """A legnagyobb, küszöböt átlépő árkülönbséget adja vissza a
        (cheap_broker, expensive_broker) pár közül, vagy None-t."""
        threshold_pct = cfg.get('open_threshold_pct', 0.05)
        best = None
        names = list(prices.keys())
        for i in range(len(names)):
            for j in range(len(names)):
                if i == j:
                    continue
                cheap_name, expensive_name = names[i], names[j]
                buy_price = prices[cheap_name]['ask']       # amit az olcsóbb brókeren fizetnénk BUY-ért
                sell_price = prices[expensive_name]['bid']  # amit a drágább brókeren kapnánk SELL-ért
                if buy_price <= 0:
                    continue
                diff_pct = (sell_price - buy_price) / buy_price * 100
                if diff_pct >= threshold_pct and (best is None or diff_pct > best['diff_pct']):
                    best = {
                        'cheap_broker': cheap_name,
                        'expensive_broker': expensive_name,
                        'buy_price': buy_price,
                        'sell_price': sell_price,
                        'diff_pct': diff_pct,
                    }
        return best

    async def _open_pair(self, symbol: str, opp: Dict, cfg: Dict):
        lots = cfg.get('lots', 0.01)
        cheap = await self._ensure_connected(opp['cheap_broker'])
        expensive = await self._ensure_connected(opp['expensive_broker'])

        logger.info(
            f"🔀 [{symbol}] Arbitrázs lehetőség: BUY @ {opp['cheap_broker']} ({opp['buy_price']}) / "
            f"SELL @ {opp['expensive_broker']} ({opp['sell_price']}) - diff {opp['diff_pct']:.3f}%"
        )

        try:
            buy_result = await cheap.place_order(symbol=symbol, side='BUY', lots=lots)
        except Exception as e:
            logger.error(f"❌ [{symbol}] Arbitrázs BUY láb kivétel ({opp['cheap_broker']}): {e}")
            return
        if not buy_result.get('success'):
            logger.error(f"❌ [{symbol}] Arbitrázs BUY láb sikertelen ({opp['cheap_broker']}): {buy_result.get('error')}")
            return

        # A SELL lábat try/except-be csomagoljuk, mert place_order elméletileg
        # kivételt is dobhat (nem csak {'success': False}-t ad vissza) - enélkül
        # a BUY láb fedezetlenül, kompenzáció nélkül maradt volna nyitva.
        sell_result = None
        sell_error = None
        try:
            sell_result = await expensive.place_order(symbol=symbol, side='SELL', lots=lots)
            if not sell_result.get('success'):
                sell_error = sell_result.get('error')
        except Exception as e:
            sell_error = str(e)

        if sell_error is not None:
            logger.error(
                f"❌ [{symbol}] Arbitrázs SELL láb sikertelen ({opp['expensive_broker']}): "
                f"{sell_error} - a BUY láb visszazárása..."
            )
            # Kompenzáció: a sikeres lábat azonnal visszazárjuk, hogy ne
            # maradjon egyoldalú, fedezetlen kitettség. Ha EZ a zárás is
            # sikertelen, a pozíciót is nyilvántartásba vesszük mint
            # "orphan" (kézi beavatkozást igénylő), hogy ne vesszen el
            # nyomtalanul a naplóból.
            try:
                compensate = await cheap.close_position(buy_result['position_id'])
                if not compensate.get('success'):
                    raise Exception(compensate.get('error', 'ismeretlen hiba'))
            except Exception as e:
                logger.error(
                    f"❌❌ [{symbol}] Kompenzáló zárás sikertelen ({opp['cheap_broker']}, "
                    f"position_id={buy_result.get('position_id')}): {e} - KÉZI BEAVATKOZÁS SZÜKSÉGES"
                )
                self._append_log({
                    'id': str(uuid.uuid4()),
                    'symbol': symbol,
                    'opened_at': datetime.now(timezone.utc).isoformat(),
                    'closed_at': datetime.now(timezone.utc).isoformat(),
                    'lots': lots,
                    'buy_broker': opp['cheap_broker'],
                    'buy_position_id': buy_result.get('position_id'),
                    'close_reason': 'orphan_compensation_failed',
                    'buy_leg_closed': False,
                    'sell_leg_closed': None,
                })
            return

        pair = {
            'id': str(uuid.uuid4()),
            'symbol': symbol,
            'opened_at': datetime.now(timezone.utc).isoformat(),
            'lots': lots,
            'buy_broker': opp['cheap_broker'],
            'buy_position_id': buy_result['position_id'],
            'buy_price': opp['buy_price'],
            'sell_broker': opp['expensive_broker'],
            'sell_position_id': sell_result['position_id'],
            'sell_price': opp['sell_price'],
            'open_diff_pct': opp['diff_pct'],
        }
        with self._state_lock:
            self.open_pairs.append(pair)
        self._save_state()
        logger.info(f"✅ [{symbol}] Arbitrázs pár megnyitva (id={pair['id']})")

    async def _manage_open_pairs(self, cfg: Dict):
        close_threshold_pct = cfg.get('close_threshold_pct', 0.01)
        timeout_seconds = cfg.get('safety_timeout_minutes', 30) * 60
        still_open = []

        with self._state_lock:
            pairs_snapshot = list(self.open_pairs)

        for pair in pairs_snapshot:
            with self._state_lock:
                prices = dict(self.latest_prices.get(pair['symbol'], {}))
            buy_broker_prices = prices.get(pair['buy_broker'])
            sell_broker_prices = prices.get(pair['sell_broker'])
            age_seconds = (
                datetime.now(timezone.utc) - datetime.fromisoformat(pair['opened_at'])
            ).total_seconds()

            current_diff_pct = None
            if buy_broker_prices and sell_broker_prices:
                # UGYANAZ az irány/formula, mint a nyitáskor (lásd
                # _find_best_opportunity): a nyitáskori "olcsó" bróker ask-ja
                # és a "drága" bróker bid-je közti szórás, most a jelenlegi
                # árakkal. Ha ez a fennmaradó árrés a nyitási értékről a
                # close_threshold_pct-re (vagy alá) zsugorodik, a lehetőség
                # konvergált. FONTOS: nem szabad a bid/ask oldalakat
                # felcserélni zárási irányra (buy_bid - sell_ask), mert az a
                # spread miatt azonnal, ténylegesen bármilyen piaci
                # állapotban negatívba fordulna, és a párt közvetlenül
                # nyitás után, hamisan "konvergáltként" zárná.
                buy_ask = buy_broker_prices['ask']
                sell_bid = sell_broker_prices['bid']
                if buy_ask > 0:
                    current_diff_pct = (sell_bid - buy_ask) / buy_ask * 100

            should_close = False
            reason = None
            if current_diff_pct is not None and current_diff_pct <= close_threshold_pct:
                should_close = True
                reason = 'convergence'
            elif age_seconds >= timeout_seconds:
                should_close = True
                reason = 'timeout'

            if should_close:
                closed_ok = await self._close_pair(pair, reason, current_diff_pct)
                if not closed_ok:
                    # Legalább az egyik láb zárása sikertelen volt - a párt
                    # NYITVA TARTJUK a nyilvántartásban, hogy a következő
                    # ciklus újra megpróbálja zárni, ahelyett hogy elveszne
                    # egy fedezetlen/félig zárt pozíció nyoma.
                    still_open.append(pair)
            else:
                still_open.append(pair)

        with self._state_lock:
            self.open_pairs = still_open
        self._save_state()

    async def _close_pair(self, pair: Dict, reason: str, close_diff_pct: Optional[float]) -> bool:
        """
        Megpróbálja zárni mindkét lábat. Visszaadja, hogy MINDKÉT láb
        sikeresen zárva van-e - ha nem, a hívó (_manage_open_pairs) a párt
        nyitva tartja a nyilvántartásban további zárási kísérletekhez, és
        egy már sikeresen zárt lábat nem próbál újra zárni (elkerülve egy
        már nem létező pozícióra hivatkozó felesleges/hibás hívást).
        """
        buy_already_closed = pair.get('_buy_leg_closed', False)
        sell_already_closed = pair.get('_sell_leg_closed', False)

        # Mindkét lábat KÜLÖN try/except-ben zárjuk, és a flag-eket egy
        # finally-ben, feltétel nélkül visszaírjuk a pair dict-be - ha ezt
        # elmulasztanánk egy kivétel esetén (pl. connect()/websocket hiba),
        # a következő ciklus egy már ténylegesen zárt lábat próbálna újra
        # zárni, vagy - rosszabb esetben - egy sikeresen zárt láb állapota
        # elveszne, és a pár örökre "nyitva ragadna" a nyilvántartásban.
        if not buy_already_closed:
            try:
                buy_server = await self._ensure_connected(pair['buy_broker'])
                buy_close = await buy_server.close_position(pair['buy_position_id'])
                buy_already_closed = buy_close.get('success', False)
                if not buy_already_closed:
                    logger.error(f"❌ [{pair['symbol']}] Arbitrázs BUY láb zárása sikertelen: {buy_close}")
            except Exception as e:
                logger.error(f"❌ [{pair['symbol']}] Arbitrázs BUY láb zárási kivétel: {e}")
            finally:
                pair['_buy_leg_closed'] = buy_already_closed

        if not sell_already_closed:
            try:
                sell_server = await self._ensure_connected(pair['sell_broker'])
                sell_close = await sell_server.close_position(pair['sell_position_id'])
                sell_already_closed = sell_close.get('success', False)
                if not sell_already_closed:
                    logger.error(f"❌ [{pair['symbol']}] Arbitrázs SELL láb zárása sikertelen: {sell_close}")
            except Exception as e:
                logger.error(f"❌ [{pair['symbol']}] Arbitrázs SELL láb zárási kivétel: {e}")
            finally:
                pair['_sell_leg_closed'] = sell_already_closed

        if not (buy_already_closed and sell_already_closed):
            return False

        entry = {
            **{k: v for k, v in pair.items() if not k.startswith('_')},
            'closed_at': datetime.now(timezone.utc).isoformat(),
            'close_reason': reason,
            'close_diff_pct': close_diff_pct,
            'buy_leg_closed': True,
            'sell_leg_closed': True,
        }
        self._append_log(entry)
        logger.info(f"✅ [{pair['symbol']}] Arbitrázs pár lezárva ({reason}, id={pair['id']})")
        return True

    def _daily_realized_pnl(self) -> float:
        """
        Megjegyzés: a lezárt párok naplója (jelenleg) nem tartalmaz valós,
        bróker-oldali realizált P&L-t (ehhez pozíciónkénti záráskori
        unrealized_pnl lekérés kellene minden close_position előtt) - ezért
        ez a védőháló a nyitási/zárási árkülönbségek alapján becsül. Ez egy
        konzervatív becslés a napi veszteséglimit betartatásához, nem
        könyvelési célú pontos eredmény.
        """
        today = datetime.now(timezone.utc).date()
        total = 0.0
        with self._state_lock:
            closed_snapshot = list(self.closed_pairs)
        for entry in closed_snapshot:
            try:
                closed_at = datetime.fromisoformat(entry['closed_at'])
            except (KeyError, ValueError):
                continue
            if closed_at.date() != today:
                continue
            open_diff = entry.get('open_diff_pct') or 0.0
            close_diff = entry.get('close_diff_pct') or 0.0
            # Pozitív, ha a spread összébb konvergált a nyitáshoz képest (jó),
            # negatív, ha kinyílt/nem konvergált (rossz) - lot-mérettel súlyozva
            # csak durva arányosításra, nem pontos USD-re.
            total += (open_diff - close_diff) * entry.get('lots', 0.01)
        return total

    def get_status_snapshot(self) -> Dict:
        """
        Konzisztens, a háttérszáltól független pillanatkép a Flask route-ok
        számára - a lock alatt csak sekély másolatot készítünk, majd a
        mutálható belső listákat/dict-eket deepcopy-zzuk, hogy egy közben
        futó _cycle() ne módosíthassa a már visszaadott, JSON-ná szerializált
        struktúrát (elkerülve a versenyhelyzetből eredő inkonzisztens vagy
        hibás szerializációt).
        """
        with self._state_lock:
            prices = copy.deepcopy(self.latest_prices)
            open_pairs = copy.deepcopy(self.open_pairs)
            closed_pairs = copy.deepcopy(list(reversed(self.closed_pairs[-50:])))
            last_error = self.last_error
        return {
            'running': self._running,
            'last_error': last_error,
            'brokers': load_brokers(),
            'config': load_config(),
            'prices': prices,
            'open_pairs': open_pairs,
            'closed_pairs': closed_pairs,
            'daily_realized_estimate': self._daily_realized_pnl(),
        }


# Singleton instance - az admin_interface importálja és route-okból hívja.
engine = ArbitrageEngine()
