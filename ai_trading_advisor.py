#!/usr/bin/env python3
"""
AI Trading Advisor
Claude AI alapú automatizált trading bot cTrader-hez
"""

import os
import json
import asyncio
import logging
import threading
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import numpy as np
from anthropic import Anthropic
from mcp_server import CTraderMCPServer, MCP_TOOLS
from news_calendar import NewsCalendar
from ml_predictor import MLPredictor

# Logging konfiguráció
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TechnicalIndicators:
    """Technikai indikátorok számítása"""

    @staticmethod
    def sma(data: List[float], period: int) -> float:
        """
        Simple Moving Average (Egyszerű mozgóátlag)

        Args:
            data: Árfolyam adatok
            period: Periódus

        Returns:
            float: SMA érték
        """
        if len(data) < period:
            return 0.0
        return np.mean(data[-period:])

    @staticmethod
    def ema(data: List[float], period: int) -> float:
        """
        Exponential Moving Average (Exponenciális mozgóátlag)

        Args:
            data: Árfolyam adatok
            period: Periódus

        Returns:
            float: EMA érték
        """
        if len(data) < period:
            return 0.0

        multiplier = 2 / (period + 1)
        ema_values = [np.mean(data[:period])]  # Kezdő SMA

        for price in data[period:]:
            ema_values.append((price - ema_values[-1]) * multiplier + ema_values[-1])

        return ema_values[-1]

    @staticmethod
    def rsi(data: List[float], period: int = 14) -> float:
        """
        Relative Strength Index (Relatív erősség index)

        Args:
            data: Árfolyam adatok
            period: Periódus (alapértelmezett: 14)

        Returns:
            float: RSI érték (0-100)
        """
        if len(data) < period + 1:
            return 50.0

        # Árfolyam változások
        deltas = np.diff(data)

        # Nyereségek és veszteségek
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        # Átlagos nyereség és veszteség
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    @staticmethod
    def bollinger_bands(data: List[float], period: int = 20, std_dev: int = 2) -> Dict[str, float]:
        """
        Bollinger Bands (Bollinger szalagok)

        Args:
            data: Árfolyam adatok
            period: Periódus
            std_dev: Szórás szorzó

        Returns:
            Dict: {'middle': középső sáv, 'upper': felső sáv, 'lower': alsó sáv}
        """
        if len(data) < period:
            return {'middle': 0.0, 'upper': 0.0, 'lower': 0.0}

        middle = np.mean(data[-period:])
        std = np.std(data[-period:])

        return {
            'middle': middle,
            'upper': middle + (std_dev * std),
            'lower': middle - (std_dev * std)
        }

    @staticmethod
    def detect_volatility_spike(candles: List[Dict], lookback: int = 20, spike_ratio: float = 2.5) -> Dict[str, Any]:
        """
        Árfolyam-alapú "lehetséges hír-esemény" észlelés API/kulcs nélkül:
        az utolsó gyertya valós tartományát (true range) hasonlítja az
        előző `lookback` gyertya átlagos true range-éhez (ATR-szerű
        közelítés). Ha a legutóbbi gyertya szokatlanul nagyot mozgott a
        megelőző átlaghoz képest, az gyakran hír/makroadat által kiváltott
        hirtelen mozgásra utal, még akkor is, ha nincs bekötve tényleges
        gazdasági naptár adat.

        Args:
            candles: OHLC gyertyák időrendben (a legrégebbi elöl, ahogy a
                get_candles() adja vissza)
            lookback: Hány megelőző gyertyából számoljunk átlagos tartományt
            spike_ratio: Az utolsó gyertya tartománya hányszorosa legyen az
                átlagnak ahhoz, hogy kiugrásnak számítson

        Returns:
            Dict: {'is_spike': bool, 'last_range': float, 'avg_range': float, 'ratio': float}
        """
        # Kell: lookback+1 gyertya a baseline-hoz (mindegyikhez egy megelőző
        # close) + 1 a legfrissebb, amit ehhez viszonyítunk.
        if len(candles) < lookback + 3:
            return {'is_spike': False, 'last_range': 0.0, 'avg_range': 0.0, 'ratio': 0.0}

        def true_range(prev_close: float, candle: Dict) -> float:
            high = candle.get('high', 0)
            low = candle.get('low', 0)
            return max(high - low, abs(high - prev_close), abs(low - prev_close))

        # Az utolsó előtti `lookback` gyertyából számolt átlag a
        # "normál" volatilitás, ehhez viszonyítjuk a legfrissebb gyertyát -
        # ha magát a legutolsót is bevonnánk az átlagba, elmosná a
        # kiugrást, amit épp észlelni akarunk. Minden baseline true range-hez
        # kell egy megelőző close is, ezért eggyel hosszabb szeletet veszünk
        # (lookback+1 gyertya), hogy pontosan `lookback` db true range jöjjön
        # ki - enélkül csak lookback-1 értékből számolt (lefelé torzított)
        # átlag adódna, ami hamis pozitív kiugrásokat eredményezne.
        baseline = candles[-(lookback + 2):-1]
        ranges = []
        for i in range(1, len(baseline)):
            ranges.append(true_range(baseline[i - 1]['close'], baseline[i]))
        avg_range = float(np.mean(ranges)) if ranges else 0.0

        last_range = true_range(candles[-2]['close'], candles[-1])
        ratio = (last_range / avg_range) if avg_range > 0 else 0.0

        return {
            'is_spike': ratio >= spike_ratio,
            'last_range': last_range,
            'avg_range': avg_range,
            'ratio': ratio
        }


class RiskManager:
    """Kockázatkezelési szabályok"""

    # Feltételezett tőkeáttétel (a cTrader Open API nem adja vissza a
    # symbol/account leverage-et a ProtoOATrader vagy ProtoOASymbol
    # üzenetekben, amikhez itt hozzáférünk), konfigurálható env változóval.
    DEFAULT_LEVERAGE = 100

    # A margin-alapú korlátnál csak a szabad egyenleg ekkora hányadát
    # engedjük egyetlen pozíció fedezetére fordítani, hogy maradjon puffer
    # árfolyamingadozásra és a többi nyitott pozícióra.
    MARGIN_SAFETY_FACTOR = 0.5

    # Kemény felső korlát a per-trade kockázatra, függetlenül a
    # MAX_RISK_PER_TRADE konfigurációtól - ez korábban hardkódolt 0.02 miatt
    # némán ignorálva volt, így egy elfelejtett/hibás config érték (pl. 0.2 =
    # 20%) most, hogy tényleg érvényesül, váratlanul túl nagy pozíciót
    # eredményezhetne. Ha valaki tudatosan nagyobb kockázatot akar, ezt a
    # konstanst kell módosítania a kódban, nem elég a configot beállítani.
    HARD_MAX_RISK_PER_TRADE = 0.05

    def __init__(self, max_risk_per_trade: Optional[float] = None, max_open_positions: Optional[int] = None):
        """
        Inicializálás

        Args:
            max_risk_per_trade: Maximum kockázat per trade (pl. 0.02 = 2%).
                Ha None, a MAX_RISK_PER_TRADE env változóból olvassa (alap: 0.02).
            max_open_positions: Maximum nyitott pozíciók száma.
                Ha None, a MAX_OPEN_POSITIONS env változóból olvassa (alap: 3).
        """
        if max_risk_per_trade is None:
            max_risk_per_trade = float(os.getenv('MAX_RISK_PER_TRADE', '0.02'))
        if max_open_positions is None:
            max_open_positions = int(os.getenv('MAX_OPEN_POSITIONS', '3'))

        if max_risk_per_trade > self.HARD_MAX_RISK_PER_TRADE:
            logger.warning(
                f"⚠️ MAX_RISK_PER_TRADE ({max_risk_per_trade:.2%}) túllépi a biztonsági "
                f"felső korlátot ({self.HARD_MAX_RISK_PER_TRADE:.2%}), levágva."
            )
            max_risk_per_trade = self.HARD_MAX_RISK_PER_TRADE

        self.max_risk_per_trade = max_risk_per_trade
        self.max_open_positions = max_open_positions
        self.leverage = float(os.getenv('CTRADER_LEVERAGE', str(self.DEFAULT_LEVERAGE)))

    @staticmethod
    def _contract_size(symbol: str) -> float:
        """
        1 lot mérete egységben, szimbólumonként (egyszerűsített közelítés,
        a valós cTrader szimbólum-specifikációt nem kérdezi le)

        Args:
            symbol: Trading szimbólum

        Returns:
            float: 1 lot mérete alapegységben
        """
        symbol = symbol.upper()
        if 'XAU' in symbol:
            return 100.0  # 1 lot arany = 100 uncia
        if 'XAG' in symbol:
            return 5000.0  # 1 lot ezüst = 5000 uncia
        if symbol.startswith('BTC') or symbol.startswith('ETH'):
            return 1.0  # 1 lot kripto = 1 egység
        return 100000.0  # sztenderd forex párok

    def estimate_used_margin(self, positions: List[Dict]) -> float:
        """
        Nyitott pozíciók fedezetigényének becslése (a fedezet-alapú
        méretezéshez), hogy egy új pozíció ne hagyja figyelmen kívül a már
        elkötelezett fedezetet.

        Args:
            positions: lista, minden elem 'symbol' (str), 'entry_price'
                (float) és 'lots' (float, LOT egységben, nem raw
                mikroegységben) kulcsokkal - a hívó felelőssége a
                get_positions() nyers ('symbol_id', 'volume' raw
                mikroegység) alakból ide konvertálni.

        Returns:
            float: becsült összesen lekötött fedezet dollárban
        """
        total = 0.0
        for p in positions or []:
            contract_size = self._contract_size(p.get('symbol') or '')
            entry_price = p.get('entry_price') or 0
            lots = p.get('lots') or 0
            notional = entry_price * contract_size * lots
            total += notional / self.leverage if self.leverage > 0 else notional
        return total

    def calculate_position_size(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss: float,
        symbol: str = "XAUUSD",
        used_margin: float = 0.0
    ) -> int:
        """
        Pozíció méret számítása kockázat alapján, szimbólumra szabott
        kontraktusmérettel

        Args:
            account_balance: Számla egyenleg
            entry_price: Belépési ár
            stop_loss: Stop loss ár
            symbol: Trading szimbólum (a kontraktusméret meghatározásához)
            used_margin: Már nyitott pozíciók által lekötött becsült fedezet
                dollárban (lásd estimate_used_margin) - ez nélkül az új
                pozíció mérete figyelmen kívül hagyná a már elkötelezett
                fedezetet, és több nyitott pozíció esetén is NOT_ENOUGH_MONEY
                hibát okozhatna.

        Returns:
            int: Volumen mikroegységben, vagy 0, ha még a bróker minimuma
            (0.01 lot) sem fér bele biztonságosan a szabad fedezetbe.
        """
        # Maximum kockázat dollárban
        max_risk_amount = account_balance * self.max_risk_per_trade

        # Ár különbség (kockázat per egység)
        price_difference = abs(entry_price - stop_loss)

        contract_size = self._contract_size(symbol)

        # A kockázat-alapú méretezés csak a stop loss távolságot ismeri, a
        # tényleges fedezetigényt (ár * kontraktusméret / tőkeáttétel) nem -
        # ez okozta, hogy pl. XAUUSD-nél (ahol 1 lot névértéke ~$400,000)
        # a kiszámolt lotméret a rendelkezésre álló fedezet többszörösét
        # igényelte, és NOT_ENOUGH_MONEY hibával elutasításra került, míg a
        # Test gomb fix, kicsi (0.01 lot) mérete mindig belefért a fedezetbe.
        # Itt korlátozzuk a lotméretet a becsült fedezetigény alapján is,
        # a már nyitott pozíciók fedezetét is figyelembe véve.
        notional_per_lot = entry_price * contract_size
        margin_per_lot = notional_per_lot / self.leverage if self.leverage > 0 else notional_per_lot
        free_margin_budget = max(account_balance * self.MARGIN_SAFETY_FACTOR - used_margin, 0)
        margin_based_lots = free_margin_budget / margin_per_lot if margin_per_lot > 0 else 0

        if price_difference == 0:
            lots = margin_based_lots
        else:
            risk_based_lots = max_risk_amount / (price_difference * contract_size)
            lots = min(risk_based_lots, margin_based_lots)

        # Mikroegységre konvertálás (100,000 mikroegység = 1 lot)
        volume_micro = int(lots * 100000)

        # Ha a biztonságosan megengedett méret a bróker minimuma (0.01 lot =
        # 1000 mikroegység) alatt van, NEM kényszerítjük fel odáig - az csak
        # egy garantált NOT_ENOUGH_MONEY elutasítást okozna. Ehelyett 0-t
        # adunk vissza, amit a hívó "nincs elég szabad fedezet, skip" jelzésként kezel.
        if volume_micro < 1000:
            return 0

        return volume_micro

    def can_open_position(self, current_positions: int) -> bool:
        """
        Ellenőrzi, hogy lehet-e új pozíciót nyitni

        Args:
            current_positions: Jelenlegi nyitott pozíciók száma

        Returns:
            bool: True ha lehet új pozíciót nyitni
        """
        return current_positions < self.max_open_positions


class AITradingAdvisor:
    """
    AI Trading Advisor - Claude AI alapú trading bot

    Funkciók:
    - Technikai analízis
    - Claude AI döntéshozatal
    - Automatikus order végrehajtás
    - Kockázatkezelés
    """

    def __init__(self, anthropic_api_key: str, symbols: Optional[List[str]] = None):
        """
        Inicializálás

        Args:
            anthropic_api_key: Anthropic API kulcs
            symbols: Kereskedett szimbólumok listája (pl. ["XAUUSD", "EURUSD"])
        """
        self.anthropic = Anthropic(api_key=anthropic_api_key)
        self.mcp_server = CTraderMCPServer()
        self.risk_manager = RiskManager()
        self.running = False
        self.symbols = symbols or ["XAUUSD"]
        self.ai_decisions_file = 'ai_decisions.json'
        self.trade_history_file = 'trade_history.json'
        self._trade_history_lock = threading.Lock()
        self._ai_decisions_lock = threading.Lock()
        self.news_calendar = NewsCalendar()
        self.ml_predictor = MLPredictor()

        logger.info(f"🤖 AI Trading Advisor inicializálva - Szimbólumok: {', '.join(self.symbols)}")

    async def start(self):
        """Trading bot indítása"""
        logger.info("🚀 Trading bot indítása...")

        try:
            # MCP szerver csatlakozás
            await self.mcp_server.connect()

            # Számla információk
            account_info = await self.mcp_server.get_account_info()
            logger.info(f"💰 Számla: ${account_info.get('balance', 0):.2f}")

            self.running = True

            # Fő loop
            while self.running:
                await self.trading_loop()

                # A ciklusidő futásidőben módosítható a Beállítások oldalon
                # (TRADING_CYCLE_SECONDS env, config.json-be mentve) - ezért
                # minden körben újraolvassuk, nem csak indításkor rögzítjük.
                # 5 másodperces darabokban várakozunk, hogy a Stop gomb
                # gyorsan hasson, akkor is, ha a beállított ciklusidő hosszú.
                try:
                    import math
                    cycle_seconds = float(os.getenv('TRADING_CYCLE_SECONDS', '60'))
                    if not math.isfinite(cycle_seconds):
                        raise ValueError("non-finite cycle interval")
                    cycle_seconds = min(max(cycle_seconds, 30), 3600)
                except (ValueError, TypeError):
                    cycle_seconds = 60
                elapsed = 0
                while elapsed < cycle_seconds:
                    if not self.running:
                        break
                    step = min(5, cycle_seconds - elapsed)
                    await asyncio.sleep(step)
                    elapsed += step

                # A websocket kapcsolat keepalive ping timeout-tal elszállhat
                # (pl. a szinkron Anthropic hívás vagy hálózati hiba miatt).
                # A self.mcp_server.authenticated flag ilyenkor NEM esik le
                # automatikusan, ezért anélkül a bot örökre halott socket-en
                # próbálkozott volna (ismétlődő "keepalive ping timeout" a
                # logban, sosem tér vissza) - minden ciklus végén ellenőrizzük
                # és szükség esetén újracsatlakozunk.
                if self.running and not self._connection_alive():
                    logger.warning("⚠️ MCP kapcsolat megszakadt, újracsatlakozás...")
                    try:
                        await self.mcp_server.close()
                    except Exception:
                        pass
                    try:
                        await self.mcp_server.connect()
                        logger.info("✅ MCP kapcsolat helyreállítva")
                    except Exception as e:
                        logger.error(f"❌ Újracsatlakozás sikertelen: {e}")

        except KeyboardInterrupt:
            logger.info("⚠️ Bot leállítva (KeyboardInterrupt)")
        except Exception as e:
            logger.error(f"❌ Hiba: {e}")
        finally:
            await self.stop()

    @staticmethod
    def _looks_like_connection_error(exc: Exception) -> bool:
        """Kapcsolat-/authentikáció-jellegű hiba felismerése, hogy csak
        ilyenkor próbáljunk azonnal újracsatlakozni (üzleti logikai hibákat,
        pl. NOT_ENOUGH_MONEY, ne kezeljünk kapcsolat-hibaként)."""
        if isinstance(exc, (ConnectionError, OSError, asyncio.TimeoutError)):
            return True
        text = str(exc).lower()
        return any(k in text for k in ("connection", "websocket", "closed", "keepalive", "ping timeout"))

    def _connection_alive(self) -> bool:
        """
        Megbízhatóbb kapcsolat-ellenőrzés, mint a self.mcp_server.authenticated
        flag: az csak explicit connect()/close() hívásra vált, egy keepalive
        ping timeout miatt elszállt socketet nem jelez.
        """
        ws = getattr(self.mcp_server, 'ws', None)
        if ws is None or not self.mcp_server.authenticated:
            return False
        closed = getattr(ws, 'closed', None)
        if closed is None:
            # Régebbi websockets verziók 'close_code'-ot használnak; ha semmi
            # nem elérhető, óvatosságból élőnek tekintjük (a következő hívás
            # hibája majd amúgy is triggereli az újracsatlakozást).
            return getattr(ws, 'close_code', None) is None
        return not closed

    async def stop(self):
        """Bot leállítása"""
        self.running = False
        await self.mcp_server.close()
        logger.info("👋 Trading bot leállítva")

    async def trading_loop(self):
        """
        Fő trading loop - végigmegy az összes konfigurált szimbólumon

        Szimbólumonként:
        1. Piaci adatok lekérése
        2. Technikai analízis
        3. Claude AI konzultáció
        4. Trading döntés végrehajtása
        """
        for symbol in self.symbols:
            await self._process_symbol(symbol)

    async def _process_symbol(self, symbol: str):
        """Egy szimbólum elemzése és kereskedési döntés végrehajtása"""
        try:
            # 1. Piaci adatok
            market_data = await self.mcp_server.get_market_data(symbol)
            candles = await self.mcp_server.get_candles(symbol, timeframe="M5", count=100)
            positions = await self.mcp_server.get_positions()
            account_info = await self.mcp_server.get_account_info()

            if not candles:
                logger.warning("⚠️ Nincs elérhető gyertyaadat")
                return

            # 2. Technikai analízis
            close_prices = [candle['close'] for candle in candles]
            analysis = self.technical_analysis(close_prices)

            # 2a. Hír/nagy-mozgás észlelés - két, egymást kiegészítő forrásból:
            # (1) árfolyam-alapú volatilitás-kiugrás (nem igényel API-kulcsot,
            #     mindig működik, de csak UTÓLAG jelzi, hogy már történt valami),
            # (2) valós gazdasági naptár (ForexFactory, publikus, kulcs
            #     nélküli feed), ami ELŐRE is jelzi a közelgő, valamint a
            #     közelmúltban megjelent közepes/magas hatású híreket.
            volatility = TechnicalIndicators.detect_volatility_spike(candles)
            try:
                news_events = await self.news_calendar.get_relevant_events(symbol, datetime.now(timezone.utc))
            except Exception as e:
                logger.warning(f"⚠️ [{symbol}] Gazdasági naptár lekérdezési hiba: {e}")
                news_events = []

            # 2c. XGBoost kiegészítő szignál - rövid távú irány-előrejelzés,
            # a friss gyertyákból tanult, memóriában tartott modellből (lásd
            # ml_predictor.py). Ez SOHA nem önálló döntés, csak egy további
            # jelzés a Claude promptban - a get_ai_decision() explicit
            # figyelmezteti erre a modellt (kis mintás, kísérleti jellegű).
            ml_signal = self.ml_predictor.predict(symbol, candles)

            # 2b. Az ehhez a szimbólumhoz tartozó már nyitott pozíció(k)
            # összegyűjtése, valós (szerver-oldali) unrealized P&L-lel - ez
            # kell ahhoz, hogy az AI ne csak új pozíció nyitásáról döntsön,
            # hanem a már futó pozíció kezeléséről (tartás/zárás/SL
            # módosítás) is, ugyanabban a - drága - Claude hívásban, hogy
            # az API-hívás tényleg mindkét döntést megérje.
            id_to_name = {
                s.get('symbolId'): name for name, s in self.mcp_server.symbols_cache.items()
            }
            own_positions = [
                p for p in positions if id_to_name.get(p.get('symbol_id')) == symbol
            ]
            if own_positions:
                try:
                    pnl_by_position = await self.mcp_server.get_positions_unrealized_pnl()
                except Exception as e:
                    logger.warning(f"⚠️ [{symbol}] Unrealized PnL lekérési hiba a pozíció-menedzsmenthez: {e}")
                    pnl_by_position = {}
                for p in own_positions:
                    server_pnl = pnl_by_position.get(p.get('position_id'))
                    p['unrealized_pnl'] = server_pnl['net'] if server_pnl else None

            # 3. Claude AI konzultáció
            decision = await self.get_ai_decision(
                symbol=symbol,
                market_data=market_data,
                analysis=analysis,
                positions=positions,
                account_info=account_info,
                own_positions=own_positions,
                volatility=volatility,
                news_events=news_events,
                ml_signal=ml_signal
            )

            # 4. Trading döntés végrehajtása
            self._record_ai_decision(symbol, decision)

            # 4a. ELŐSZÖR a már nyitott pozíció(k) kezelése (tartás/zárás/
            # SL-módosítás), CSAK EZUTÁN az esetleges új belépés. Ez azért
            # fontos, mert execute_trade() a max_open_positions korlátot a
            # get_positions() FRISS állapotán ellenőrzi - ha az AI ugyanebben
            # a körben zárni akarja a régi pozíciót és nyitni egy újat (pl.
            # megfordult a jelzés), a zárásnak meg kell előznie az új
            # megbízást, különben a régi pozíció feleslegesen blokkolja a
            # limitet, és az új belépés csak a következő ciklusban futna le.
            if own_positions:
                await self._manage_open_positions(symbol, own_positions, decision.get('position_management'), market_data)

            if decision['action'] != 'HOLD':
                await self.execute_trade(symbol, decision, market_data, account_info)

            logger.info(f"✅ [{symbol}] Trading loop befejezve - Döntés: {decision['action']}")

        except Exception as e:
            logger.error(f"❌ [{symbol}] Trading loop hiba: {e}")
            if self._looks_like_connection_error(e):
                # Ne várjunk a ciklus végéig (akár ~1 percig) egy elszállt
                # kapcsolat újraélesztésével - azonnal próbáljunk
                # újracsatlakozni, hogy a következő szimbólum (vagy a
                # dashboard lekérdezései) minél előbb friss adatot kapjanak.
                logger.warning("⚠️ Kapcsolat-jellegű hiba, azonnali újracsatlakozás...")
                try:
                    await self.mcp_server.close()
                    await self.mcp_server.connect()
                    logger.info("✅ MCP kapcsolat helyreállítva")
                except Exception as reconnect_error:
                    logger.error(f"❌ Újracsatlakozás sikertelen: {reconnect_error}")

    def _record_ai_decision(self, symbol: str, decision: Dict[str, Any], max_entries: int = 50):
        """Minden AI döntés (HOLD is) elmentése egy visszajelzési panelhez -
        ez különbözik a trade_history.json-tól, ami csak a ténylegesen
        végrehajtott megbízásokat listázza. Fájlba írjuk, hogy az admin
        felület (Flask, más processz-szálon) is olvashassa."""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'action': decision.get('action', 'HOLD'),
            'confidence': decision.get('confidence', 0.0),
            'reasoning': decision.get('reasoning', ''),
            'stop_loss_pips': decision.get('stop_loss_pips'),
            'take_profit_pips': decision.get('take_profit_pips'),
        }
        # Lock: csak ez az egyetlen bot-szál ír a fájlba, de több egymást
        # átfedő trading loop híváskor (elméletben) elkerüli az össze-vissza
        # írást. Atomi csere (tmp fájl + os.replace) véd az ellen, hogy a
        # Flask oldali /api/ai-decisions olvasó félig kiírt/csonka fájlt
        # kapjon, mivel az os.replace egyetlen atomi rename-művelet.
        with self._ai_decisions_lock:
            try:
                decisions = []
                if os.path.exists(self.ai_decisions_file):
                    with open(self.ai_decisions_file, 'r') as f:
                        decisions = json.load(f)
                decisions.append(entry)
                decisions = decisions[-max_entries:]
                tmp_path = f"{self.ai_decisions_file}.tmp"
                with open(tmp_path, 'w') as f:
                    json.dump(decisions, f)
                os.replace(tmp_path, self.ai_decisions_file)
            except (OSError, json.JSONDecodeError) as e:
                logger.error(f"AI döntés mentési hiba: {e}")

    def _record_trade_history(
        self,
        symbol: str,
        action: str,
        volume_lots: float,
        entry_price: float,
        status: str,
        reasoning: str = '',
        pnl: Optional[float] = None,
        max_entries: int = 50
    ):
        """Egy ténylegesen leadott (sikeres vagy elutasított) megbízás elmentése
        a Kereskedési Előzmények panelhez - ez különbözik az ai_decisions.json-tól,
        ami MINDEN AI döntést listáz (HOLD is), függetlenül attól, hogy lett-e
        belőle valós megbízás."""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'type': action,
            'action': status,
            'volume': volume_lots,
            'entry_price': entry_price,
            'pnl': pnl,
            'reasoning': reasoning,
        }
        with self._trade_history_lock:
            try:
                history = []
                if os.path.exists(self.trade_history_file):
                    with open(self.trade_history_file, 'r') as f:
                        history = json.load(f)
                history.append(entry)
                history = history[-max_entries:]
                tmp_path = f"{self.trade_history_file}.tmp"
                with open(tmp_path, 'w') as f:
                    json.dump(history, f)
                os.replace(tmp_path, self.trade_history_file)
            except (OSError, json.JSONDecodeError) as e:
                logger.error(f"Kereskedési előzmény mentési hiba: {e}")

    def technical_analysis(self, close_prices: List[float]) -> Dict[str, Any]:
        """
        Technikai analízis végrehajtása

        Args:
            close_prices: Záróár lista

        Returns:
            Dict: Analízis eredmények
        """
        indicators = TechnicalIndicators()

        # Mozgóátlagok
        sma_20 = indicators.sma(close_prices, 20)
        sma_50 = indicators.sma(close_prices, 50)
        ema_20 = indicators.ema(close_prices, 20)

        # RSI
        rsi = indicators.rsi(close_prices, 14)

        # Bollinger Bands
        bb = indicators.bollinger_bands(close_prices, 20, 2)

        # Trend meghatározás
        current_price = close_prices[-1]
        trend = 'BULLISH' if sma_20 > sma_50 else 'BEARISH'

        analysis = {
            'current_price': current_price,
            'sma_20': sma_20,
            'sma_50': sma_50,
            'ema_20': ema_20,
            'rsi': rsi,
            'bollinger_upper': bb['upper'],
            'bollinger_middle': bb['middle'],
            'bollinger_lower': bb['lower'],
            'trend': trend
        }

        logger.info(f"📊 Analízis: Trend={trend}, RSI={rsi:.2f}, Price={current_price:.2f}")
        return analysis

    async def get_ai_decision(
        self,
        symbol: str,
        market_data: Dict,
        analysis: Dict,
        positions: List,
        account_info: Dict,
        own_positions: Optional[List[Dict]] = None,
        volatility: Optional[Dict] = None,
        news_events: Optional[List[Dict]] = None,
        ml_signal: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Claude AI döntéskérés

        Args:
            symbol: Trading szimbólum
            market_data: Piaci adatok
            analysis: Technikai analízis eredmények
            positions: Jelenlegi pozíciók (az összes szimbólumon)
            account_info: Számla információk
            own_positions: Az ehhez a szimbólumhoz tartozó már nyitott
                pozíció(k), valós unrealized_pnl-lel kiegészítve - ha van
                ilyen, az AI-t a pozíció kezeléséről (tartás/zárás/SL
                módosítás) is megkérdezzük, ugyanabban a hívásban, mint az
                új-pozíció döntést (nem duplázzuk az amúgy is drága Claude
                hívások számát).
            volatility: TechnicalIndicators.detect_volatility_spike() eredménye
                - jelzi, ha a legutóbbi gyertya szokatlanul nagyot mozgott
                (lehetséges hír-esemény, akkor is, ha nincs naptár-adat).
            news_events: NewsCalendar.get_relevant_events() eredménye - a
                szimbólum devizáihoz tartozó, közel-múltbeli/közelgő
                közepes/magas hatású gazdasági események.
            ml_signal: MLPredictor.predict() eredménye - egy XGBoost modell
                kis mintás, kísérleti irány-előrejelzése. Csak kiegészítő
                szignálként adjuk a promptba, sosem parancsként.

        Returns:
            Dict: Trading döntés
        """
        try:
            own_positions = own_positions or []
            volatility = volatility or {}
            news_events = news_events or []

            if volatility.get('is_spike'):
                volatility_block = (
                    f"\n**⚠️ Volatility Alert:** The most recent candle's range is "
                    f"{volatility.get('ratio', 0):.1f}x the recent average - this often "
                    f"indicates a news/data release just moved the market. Be more cautious: "
                    f"prefer protecting existing positions and be more selective about new entries.\n"
                )
            else:
                volatility_block = ""

            if news_events:
                news_lines = []
                for ev in news_events:
                    when = f"in {ev['minutes_from_now']} min" if ev['minutes_from_now'] >= 0 else f"{abs(ev['minutes_from_now'])} min ago"
                    news_lines.append(
                        f"- [{ev['impact']}] {ev['country']} {ev['title']} ({when}) "
                        f"forecast={ev.get('forecast') or 'n/a'} previous={ev.get('previous') or 'n/a'}"
                    )
                news_block = (
                    "\n**📰 Economic Calendar (medium/high impact, this symbol's currencies):**\n"
                    + "\n".join(news_lines)
                    + "\n\nIf a high-impact event is imminent (within ~30 min), strongly prefer HOLD for "
                    "new entries (spreads widen and moves become erratic/unpredictable around the release), "
                    "and consider tightening stops or reducing size on existing positions. If an event just "
                    "happened, use it to explain any volatility alert above rather than assuming a technical breakout.\n"
                )
            else:
                news_block = ""

            if ml_signal:
                ml_block = (
                    f"\n**🤖 ML Supplemental Signal (XGBoost, experimental/low-sample):** "
                    f"{ml_signal['signal']} (P(up) over next {ml_signal['lookahead_candles']} "
                    f"M5 candles = {ml_signal['probability_up']:.2f}, trained on only "
                    f"{ml_signal['trained_samples']} in-memory samples for this symbol). "
                    "This is a weak, self-supervised, short-horizon statistical signal - "
                    "treat it as a minor tie-breaker alongside the technical analysis, NOT "
                    "as a standalone reason to trade. Ignore it if it conflicts with the "
                    "trend/RSI/news picture above.\n"
                )
            else:
                ml_block = ""

            if own_positions:
                positions_block_lines = []
                for p in own_positions:
                    pnl = p.get('unrealized_pnl')
                    pnl_text = f"${pnl:.2f}" if pnl is not None else "n/a"
                    positions_block_lines.append(
                        f"- Position ID {p.get('position_id')}: {p.get('side')} "
                        f"{(p.get('volume') or 0) / 10_000_000:.2f} lots @ {p.get('entry_price')}, "
                        f"unrealized P&L: {pnl_text}"
                    )
                own_positions_block = (
                    "**Your Open Position(s) on " + symbol + ":**\n"
                    + "\n".join(positions_block_lines)
                    + "\n\nYou must ALSO decide how to manage this/these existing position(s) - "
                    "not just whether to open a new one. Consider: is the original setup still "
                    "valid given the current technicals, has the trend reversed, is there an "
                    "unusually large/fast price move (possible news event) that warrants "
                    "tightening the stop or closing early to protect profit, or should you let "
                    "it run to the original target?"
                )
                position_management_schema = """,
    "position_management": {
        "action": "HOLD" or "CLOSE" or "MOVE_SL",
        "position_id": the Position ID from the list above this decision applies to,
        "new_stop_loss": new stop loss price (ONLY required if action is MOVE_SL, e.g. to move to break-even or trail behind price),
        "reasoning": "why you chose this action for the existing position"
    } (if there are MULTIPLE open positions listed above, make "position_management" a JSON ARRAY of one such object per position instead of a single object)"""
            else:
                own_positions_block = "**Your Open Position(s) on " + symbol + ":** none"
                position_management_schema = ""

            # Prompt összeállítása
            prompt = f"""
You are an expert trading advisor analyzing {symbol}.

**Current Market Data:**
- Bid: {market_data.get('bid', 0)}
- Ask: {market_data.get('ask', 0)}
- Spread: {market_data.get('spread', 0)}

**Technical Analysis:**
- Current Price: {analysis['current_price']:.2f}
- SMA 20: {analysis['sma_20']:.2f}
- SMA 50: {analysis['sma_50']:.2f}
- EMA 20: {analysis['ema_20']:.2f}
- RSI: {analysis['rsi']:.2f}
- Bollinger Upper: {analysis['bollinger_upper']:.2f}
- Bollinger Middle: {analysis['bollinger_middle']:.2f}
- Bollinger Lower: {analysis['bollinger_lower']:.2f}
- Trend: {analysis['trend']}

**Current Positions:**
- Open Positions (all symbols): {len(positions)}
{volatility_block}{news_block}{ml_block}
{own_positions_block}

**Account Info:**
- Balance: ${account_info.get('balance', 0):.2f}

**Trading Rules:**
- Maximum Risk per Trade: 2%
- RSI Overbought: > 70 (consider SELL)
- RSI Oversold: < 30 (consider BUY)
- Follow the trend
- Use stop loss and take profit

Based on this analysis, provide your trading decision in this EXACT JSON format:
{{
    "action": "BUY" or "SELL" or "HOLD",
    "confidence": 0.0 to 1.0,
    "reasoning": "your detailed reasoning",
    "stop_loss_pips": number of pips for stop loss (e.g., 20),
    "take_profit_pips": number of pips for take profit (e.g., 40){position_management_schema}
}}

"action"/"confidence"/"reasoning"/"stop_loss_pips"/"take_profit_pips" are about a POTENTIAL NEW position.
{"Include \"position_management\" for the existing position(s) listed above." if own_positions else "Omit \"position_management\" entirely since there is no open position on this symbol."}

Provide ONLY the JSON, no other text.
"""

            # Claude API hívás - a szinkron Anthropic klienst külön szálon kell futtatni,
            # különben blokkolja az asyncio event loop-ot a hívás teljes idejére (~5-10s),
            # ami kiéhezteti a websocket kapcsolat keepalive ping/pong kezelését és
            # "keepalive ping timeout" hibát okoz a cTrader kapcsolaton.
            response = await asyncio.to_thread(
                self.anthropic.messages.create,
                model="claude-sonnet-4-5",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            # Válasz feldolgozása
            decision_text = response.content[0].text.strip()

            # JSON kinyerése (ha van egyéb szöveg is)
            if '```json' in decision_text:
                decision_text = decision_text.split('```json')[1].split('```')[0].strip()
            elif '```' in decision_text:
                decision_text = decision_text.split('```')[1].split('```')[0].strip()

            decision = json.loads(decision_text)

            logger.info(f"🤖 AI Döntés: {decision.get('action')} (confidence: {decision.get('confidence', 0):.2f})")
            logger.info(f"💭 Indoklás: {decision.get('reasoning', '')}")
            pos_mgmt = decision.get('position_management')
            if pos_mgmt:
                # Több nyitott pozíció esetén Claude tömböt is visszaadhat
                # (lásd position_management_schema) - a logolásnak ezt is
                # kezelnie kell, különben egy .get() hívás listán elszállna,
                # és a teljes döntés HOLD-ra esne vissza (lásd korábbi hiba).
                pos_mgmt_entries = pos_mgmt if isinstance(pos_mgmt, list) else [pos_mgmt]
                for entry in pos_mgmt_entries:
                    if isinstance(entry, dict):
                        logger.info(
                            f"🛠️ [{symbol}] Pozíció-menedzsment döntés: {entry.get('action')} "
                            f"(id={entry.get('position_id')}) - {entry.get('reasoning', '')}"
                        )
                    else:
                        logger.warning(f"⚠️ [{symbol}] Érvénytelen position_management bejegyzés a logban: {entry!r}")

            return decision

        except Exception as e:
            logger.error(f"❌ AI döntés hiba: {e}")
            return {
                'action': 'HOLD',
                'confidence': 0.0,
                'reasoning': f'Error: {e}',
                'stop_loss_pips': 0,
                'take_profit_pips': 0,
                'position_management': None
            }

    async def _manage_open_positions(
        self,
        symbol: str,
        own_positions: List[Dict],
        position_management: Optional[Any],
        market_data: Dict
    ):
        """
        A már nyitott pozíció(k) kezelése az AI döntése alapján: tartás,
        zárás, vagy SL módosítás (pl. break-even-re húzás, trailing stop,
        vagy védekező szűkítés hír/nagy mozgás esetén).

        Ha az AI nem adott position_management-et (pl. hibás válasz, vagy
        a régi promptformátum), HOLD-nak tekintjük - nem csinálunk semmit,
        a pozíció változatlanul fut tovább a saját SL/TP-jével.

        Több nyitott pozíció esetén az AI-t egy JSON TÖMB visszaadására
        kérjük (egy elem/pozíció) - de védekezésből egyetlen objektumot is
        elfogadunk (akkor is, ha több pozíció van), mert a modell néha csak
        egyet ad vissza; ilyenkor csak az az egy pozíció kap kezelést.
        """
        if not position_management:
            return

        entries = position_management if isinstance(position_management, list) else [position_management]
        for entry in entries:
            if isinstance(entry, dict):
                await self._apply_position_management(symbol, own_positions, entry, market_data)
            else:
                logger.warning(f"⚠️ [{symbol}] Érvénytelen position_management bejegyzés (nem dict): {entry!r}")

    async def _apply_position_management(
        self,
        symbol: str,
        own_positions: List[Dict],
        position_management: Dict,
        market_data: Dict
    ):
        """Egyetlen position_management bejegyzés végrehajtása - lásd
        _manage_open_positions, ami egy vagy több ilyen bejegyzést hívhat."""
        action = (position_management.get('action') or 'HOLD').upper()
        target_id = position_management.get('position_id')

        # Ha az AI nem (vagy hibásan) adott meg position_id-t, és csak egy
        # nyitott pozíció van ezen a szimbólumon, egyértelmű, melyikről van szó.
        target_position = next(
            (p for p in own_positions if p.get('position_id') == target_id),
            own_positions[0] if len(own_positions) == 1 else None
        )

        if action == 'HOLD' or not target_position:
            if action != 'HOLD':
                logger.warning(
                    f"⚠️ [{symbol}] Pozíció-menedzsment: '{action}' de nem található "
                    f"egyértelmű pozíció (id={target_id}), kihagyva"
                )
            return

        position_id = target_position.get('position_id')

        if action == 'CLOSE':
            result = await self.mcp_server.close_position(position_id)
            if result.get('success'):
                logger.info(f"✅ [{symbol}] Pozíció zárva AI döntés alapján (id={position_id})")
                # Megjegyzés: a 'pnl' itt a zárás-kérés PILLANATA ELŐTTI
                # szerver-oldali unrealized P&L (lásd _process_symbol), NEM
                # a tényleges realizált P&L a zárási executiontől - a
                # PROTO_OA_EXECUTION_EVENT válasz a close_position()-nél nem
                # tartalmazza közvetlenül a realizált eredményt. Kis
                # csúszástól eltekintve (a zárás közben eltelt pár száz ms
                # alatti árváltozás) jó közelítés, de éles auditáláshoz a
                # cTrader saját history/deal-lekérdezését kellene használni.
                self._record_trade_history(
                    symbol=symbol,
                    action=target_position.get('side', ''),
                    volume_lots=(target_position.get('volume') or 0) / 10_000_000,
                    entry_price=target_position.get('entry_price', 0),
                    status='AI által zárva',
                    reasoning=position_management.get('reasoning', ''),
                    pnl=target_position.get('unrealized_pnl')
                )
            else:
                logger.error(f"❌ [{symbol}] Pozíció zárása sikertelen (id={position_id}): {result.get('error')}")

        elif action == 'MOVE_SL':
            new_stop_loss = position_management.get('new_stop_loss')
            if not new_stop_loss:
                logger.warning(f"⚠️ [{symbol}] MOVE_SL de nincs new_stop_loss megadva, kihagyva")
                return

            try:
                new_stop_loss = float(new_stop_loss)
            except (TypeError, ValueError):
                logger.warning(f"⚠️ [{symbol}] MOVE_SL érvénytelen new_stop_loss ({new_stop_loss}), kihagyva")
                return

            # Biztonsági ellenőrzés, mielőtt bármit is elküldenénk a
            # brókernek: az AI hibás/téves válasza NE tudjon a pozíció
            # oldalával ellentétes (azonnal kiütő), vagy a jelenlegi
            # védelemnél kockázatosabb (a meglévő SL-nél lazább) stopot
            # beállítani. Csak a kockázatot CSÖKKENTŐ (szorosabb) módosítást
            # engedünk át - ez lefedi a break-even-re húzást és a trailing
            # stopot is, de kizárja a véletlen kockázat-növelést.
            side = target_position.get('side')
            current_price = market_data.get('bid') if side == 'SELL' else market_data.get('ask')
            existing_sl = target_position.get('stop_loss')

            # Fail-closed: ha nincs érvényes aktuális ár (pl. hibás/hiányos
            # market_data), NEM küldjük el a módosítást találgatva - inkább
            # kihagyjuk ebben a körben, mint hogy egy esetlegesen már
            # kiütő/érvénytelen SL-t engedjünk át ellenőrzés nélkül.
            if not current_price:
                logger.warning(
                    f"⚠️ [{symbol}] MOVE_SL elutasítva: nincs érvényes aktuális ár a biztonsági "
                    f"ellenőrzéshez, kihagyva"
                )
                return

            if side == 'BUY' and new_stop_loss >= current_price:
                logger.warning(
                    f"⚠️ [{symbol}] MOVE_SL elutasítva: BUY pozíciónál az új SL ({new_stop_loss}) "
                    f"nem lehet az aktuális ár ({current_price}) felett, kihagyva"
                )
                return
            if side == 'SELL' and new_stop_loss <= current_price:
                logger.warning(
                    f"⚠️ [{symbol}] MOVE_SL elutasítva: SELL pozíciónál az új SL ({new_stop_loss}) "
                    f"nem lehet az aktuális ár ({current_price}) alatt, kihagyva"
                )
                return
            if existing_sl:
                if side == 'BUY' and new_stop_loss < existing_sl:
                    logger.warning(
                        f"⚠️ [{symbol}] MOVE_SL elutasítva: az új SL ({new_stop_loss}) lazább lenne, "
                        f"mint a jelenlegi ({existing_sl}) - csak szorosabb SL engedélyezett, kihagyva"
                    )
                    return
                if side == 'SELL' and new_stop_loss > existing_sl:
                    logger.warning(
                        f"⚠️ [{symbol}] MOVE_SL elutasítva: az új SL ({new_stop_loss}) lazább lenne, "
                        f"mint a jelenlegi ({existing_sl}) - csak szorosabb SL engedélyezett, kihagyva"
                    )
                    return

            try:
                symbol_id = await self.mcp_server.get_symbol_id(symbol)
                symbol_details = await self.mcp_server.get_symbol_details(symbol_id) if symbol_id else {}
                digits = symbol_details.get('digits')
            except Exception as e:
                logger.warning(f"⚠️ [{symbol}] Symbol digits lekérési hiba SL módosításhoz: {e}")
                digits = None

            result = await self.mcp_server.amend_position_sltp(
                position_id=position_id,
                stop_loss=new_stop_loss,
                symbol_digits=digits
            )
            if result.get('success'):
                logger.info(f"✅ [{symbol}] SL módosítva AI döntés alapján (id={position_id}): {new_stop_loss}")
            else:
                logger.error(f"❌ [{symbol}] SL módosítás sikertelen (id={position_id}): {result.get('error')}")

        else:
            logger.warning(f"⚠️ [{symbol}] Ismeretlen position_management action: {action}")

    async def execute_trade(
        self,
        symbol: str,
        decision: Dict,
        market_data: Dict,
        account_info: Dict
    ):
        """
        Trading döntés végrehajtása

        Args:
            symbol: Trading szimbólum
            decision: AI döntés
            market_data: Piaci adatok
            account_info: Számla információk
        """
        try:
            # Kockázatkezelés ellenőrzése
            positions = await self.mcp_server.get_positions()
            if not self.risk_manager.can_open_position(len(positions)):
                logger.warning(f"⚠️ [{symbol}] Maximum nyitott pozíciók száma elérve")
                return

            # Confidence threshold
            if decision['confidence'] < 0.6:
                logger.info(f"⚠️ [{symbol}] Alacsony confidence ({decision['confidence']:.2f}), skip trade")
                return

            action = decision['action']

            # Entry price
            entry_price = market_data['ask'] if action == 'BUY' else market_data['bid']

            # Stop Loss és Take Profit számítása (pip-ben)
            # Az AI által adott pip értékek túl kicsik lehetnek (pl. 1-2 pip),
            # ami a bróker minimum stop-távolsága alá esik és TRADING_BAD_STOPS
            # hibát okoz - ezért egy ésszerű minimumra korlátozzuk.
            MIN_STOP_PIPS = 10
            pip_value = self._pip_value(symbol)
            stop_loss_pips = max(decision.get('stop_loss_pips', 20) or 20, MIN_STOP_PIPS)
            take_profit_pips = max(decision.get('take_profit_pips', 40) or 40, MIN_STOP_PIPS)
            stop_loss_distance = stop_loss_pips * pip_value
            take_profit_distance = take_profit_pips * pip_value

            if action == 'BUY':
                stop_loss = entry_price - stop_loss_distance
                take_profit = entry_price + take_profit_distance
            else:
                stop_loss = entry_price + stop_loss_distance
                take_profit = entry_price - take_profit_distance

            # Már nyitott pozíciók becsült fedezetigénye, hogy az új pozíció
            # mérete ne hagyja figyelmen kívül a már elkötelezett fedezetet
            # (több nyitott pozíció esetén ez nélkül is NOT_ENOUGH_MONEY
            # eredményezhető, még ha egyenként belefértek is).
            id_to_name = {
                s.get('symbolId'): name for name, s in self.mcp_server.symbols_cache.items()
            }
            positions_for_margin = []
            for p in positions:
                resolved_name = id_to_name.get(p.get('symbol_id'))
                if resolved_name is None:
                    # Ismeretlen symbol_id (pl. symbols_cache még nem töltött be
                    # egy adott szimbólumot) - NEM feltételezzük, hogy a most
                    # kereskedett szimbólummal egyezik (ez XAU vs. forex esetén
                    # nagyságrendekkel elszámolná a fedezetet), hanem a
                    # legnagyobb ismert kontraktusméretet (XAU) használjuk
                    # legrosszabb esetként, hogy inkább alul-, mint felül-
                    # becsüljük a szabad fedezetet.
                    resolved_name = 'XAUUSD'
                positions_for_margin.append({
                    'symbol': resolved_name,
                    'entry_price': p.get('entry_price') or 0,
                    'lots': (p.get('volume') or 0) / 10_000_000,
                })
            used_margin = self.risk_manager.estimate_used_margin(positions_for_margin)

            # Pozíció méret számítása
            volume = self.risk_manager.calculate_position_size(
                account_balance=account_info['balance'],
                entry_price=entry_price,
                stop_loss=stop_loss,
                symbol=symbol,
                used_margin=used_margin
            )

            if volume <= 0:
                logger.warning(
                    f"⚠️ [{symbol}] Nincs elég szabad fedezet egy új pozícióhoz "
                    f"(lekötött fedezet: ${used_margin:.2f}), trade kihagyva"
                )
                return

            # Megbízás leadása (volume mikroegységben -> lot konverzió)
            # A kockázat-alapú méretezés nem ismeri a brókernél elérhető
            # tőkeáttételt/fedezetigényt, ezért drága instrumentumoknál
            # (pl. XAUUSD) NOT_ENOUGH_MONEY hibát okozhat. Ilyenkor a
            # lotméretet felezve újrapróbálkozunk, amíg a bróker minimuma
            # alá nem érünk vagy más jellegű hibát nem kapunk.
            lots = volume / 100000
            order_result = None
            for attempt in range(4):
                order_result = await self.mcp_server.place_order(
                    symbol=symbol,
                    side=action,
                    lots=lots,
                    stop_loss=stop_loss,
                    take_profit=take_profit
                )
                if order_result.get('success'):
                    break
                error_text = str(order_result.get('error', ''))
                if 'NOT_ENOUGH_MONEY' in error_text and lots > 0.01:
                    new_lots = round(max(lots / 2, 0.01), 2)
                    logger.warning(
                        f"⚠️ [{symbol}] Fedezethiány {lots:.2f} lot mellett, "
                        f"újrapróbálkozás {new_lots:.2f} lottal"
                    )
                    lots = new_lots
                    continue
                break

            if order_result.get('success'):
                logger.info(f"✅ [{symbol}] Trade végrehajtva: {action} {lots:.2f} lot @ {entry_price:.2f}")
                logger.info(f"   SL: {stop_loss:.2f}, TP: {take_profit:.2f}")
                self._record_trade_history(
                    symbol=symbol,
                    action=action,
                    volume_lots=lots,
                    entry_price=entry_price,
                    status=order_result.get('status', 'végrehajtva'),
                    reasoning=decision.get('reasoning', '')
                )
            else:
                logger.error(f"❌ [{symbol}] Trade hiba: {order_result.get('error')}")
                self._record_trade_history(
                    symbol=symbol,
                    action=action,
                    volume_lots=lots,
                    entry_price=entry_price,
                    status=f"elutasítva: {order_result.get('error', 'ismeretlen hiba')}",
                    reasoning=decision.get('reasoning', '')
                )

        except Exception as e:
            logger.error(f"❌ [{symbol}] Trade végrehajtási hiba: {e}")
            if self._looks_like_connection_error(e):
                # Ugyanaz a self-healing, mint _process_symbol-ban: ne várjunk
                # a ciklus végéig egy elszállt kapcsolattal - a trade-végrehajtás
                # is kapcsolat-hibába futhat (pl. get_positions/place_order),
                # ilyenkor azonnal próbáljunk újracsatlakozni.
                logger.warning("⚠️ Kapcsolat-jellegű hiba trade végrehajtás közben, azonnali újracsatlakozás...")
                try:
                    await self.mcp_server.close()
                    await self.mcp_server.connect()
                    logger.info("✅ MCP kapcsolat helyreállítva")
                except Exception as reconnect_error:
                    logger.error(f"❌ Újracsatlakozás sikertelen: {reconnect_error}")

    @staticmethod
    def _pip_value(symbol: str) -> float:
        """
        1 pip mérete szimbólumonként (egyszerűsített közelítés)

        Args:
            symbol: Trading szimbólum

        Returns:
            float: 1 pip mérete árfolyam-egységben
        """
        symbol = symbol.upper()
        if 'XAU' in symbol or 'XAG' in symbol:
            return 0.1  # arany/ezüst
        if 'JPY' in symbol:
            return 0.01  # JPY párok
        if symbol.startswith('BTC') or symbol.startswith('ETH'):
            return 1.0  # kripto
        return 0.0001  # sztenderd forex párok


async def main():
    """Főprogram"""
    print("=" * 60)
    print("🤖 AI Trading Advisor - Claude AI + cTrader")
    print("=" * 60)

    # API kulcs ellenőrzés
    anthropic_api_key = os.getenv('ANTHROPIC_API_KEY')
    if not anthropic_api_key:
        print("\n❌ HIBA: ANTHROPIC_API_KEY környezeti változó nincs beállítva!")
        print("   Használat: export ANTHROPIC_API_KEY='your-api-key'")
        return

    # Credentials ellenőrzés
    if not os.path.exists('credentials.json'):
        print("\n❌ HIBA: credentials.json nem található!")
        print("   Először futtasd: python ctrader_oauth_setup.py")
        return

    print("\n✅ Minden rendben, bot indítása...")
    print("=" * 60)

    # Bot indítása
    advisor = AITradingAdvisor(anthropic_api_key)

    try:
        await advisor.start()
    except KeyboardInterrupt:
        print("\n\n⚠️ Bot leállítva (Ctrl+C)")
        await advisor.stop()


if __name__ == "__main__":
    asyncio.run(main())
