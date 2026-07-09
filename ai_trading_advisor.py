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
from datetime import datetime
import numpy as np
from anthropic import Anthropic
from mcp_server import CTraderMCPServer, MCP_TOOLS

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


class RiskManager:
    """Kockázatkezelési szabályok"""

    def __init__(self, max_risk_per_trade: float = 0.02, max_open_positions: int = 3):
        """
        Inicializálás

        Args:
            max_risk_per_trade: Maximum kockázat per trade (pl. 0.02 = 2%)
            max_open_positions: Maximum nyitott pozíciók száma
        """
        self.max_risk_per_trade = max_risk_per_trade
        self.max_open_positions = max_open_positions

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

    def calculate_position_size(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss: float,
        symbol: str = "XAUUSD"
    ) -> int:
        """
        Pozíció méret számítása kockázat alapján, szimbólumra szabott
        kontraktusmérettel

        Args:
            account_balance: Számla egyenleg
            entry_price: Belépési ár
            stop_loss: Stop loss ár
            symbol: Trading szimbólum (a kontraktusméret meghatározásához)

        Returns:
            int: Volumen mikroegységben
        """
        # Maximum kockázat dollárban
        max_risk_amount = account_balance * self.max_risk_per_trade

        # Ár különbség (kockázat per egység)
        price_difference = abs(entry_price - stop_loss)

        if price_difference == 0:
            return 10000  # 0.01 lot alapértelmezett

        contract_size = self._contract_size(symbol)

        # Lot méret számítása: mennyi lot mellett éri el a kockázat a max_risk_amount-ot
        # dollár_kockázat_per_lot = price_difference * contract_size
        lots = max_risk_amount / (price_difference * contract_size)

        # Mikroegységre konvertálás (100,000 mikroegység = 1 lot)
        volume_micro = int(lots * 100000)

        # Minimum 0.01 lot (1000 mikroegység, mivel 1000/100000 = 0.01 lot)
        return max(volume_micro, 1000)

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
        self.risk_manager = RiskManager(max_risk_per_trade=0.02, max_open_positions=3)
        self.running = False
        self.symbols = symbols or ["XAUUSD"]
        self.ai_decisions_file = 'ai_decisions.json'
        self.trade_history_file = 'trade_history.json'
        self._trade_history_lock = threading.Lock()
        self._ai_decisions_lock = threading.Lock()

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

                # 1 perc várakozás, de 5 másodpercenként ellenőrizzük a leállítást,
                # hogy a Stop gomb gyorsan hasson
                for _ in range(12):
                    if not self.running:
                        break
                    await asyncio.sleep(5)

        except KeyboardInterrupt:
            logger.info("⚠️ Bot leállítva (KeyboardInterrupt)")
        except Exception as e:
            logger.error(f"❌ Hiba: {e}")
        finally:
            await self.stop()

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

            # 3. Claude AI konzultáció
            decision = await self.get_ai_decision(
                symbol=symbol,
                market_data=market_data,
                analysis=analysis,
                positions=positions,
                account_info=account_info
            )

            # 4. Trading döntés végrehajtása
            self._record_ai_decision(symbol, decision)

            if decision['action'] != 'HOLD':
                await self.execute_trade(symbol, decision, market_data, account_info)

            logger.info(f"✅ [{symbol}] Trading loop befejezve - Döntés: {decision['action']}")

        except Exception as e:
            logger.error(f"❌ [{symbol}] Trading loop hiba: {e}")

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
        account_info: Dict
    ) -> Dict[str, Any]:
        """
        Claude AI döntéskérés

        Args:
            symbol: Trading szimbólum
            market_data: Piaci adatok
            analysis: Technikai analízis eredmények
            positions: Jelenlegi pozíciók
            account_info: Számla információk

        Returns:
            Dict: Trading döntés
        """
        try:
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
- Open Positions: {len(positions)}

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
    "take_profit_pips": number of pips for take profit (e.g., 40)
}}

Provide ONLY the JSON, no other text.
"""

            # Claude API hívás - a szinkron Anthropic klienst külön szálon kell futtatni,
            # különben blokkolja az asyncio event loop-ot a hívás teljes idejére (~5-10s),
            # ami kiéhezteti a websocket kapcsolat keepalive ping/pong kezelését és
            # "keepalive ping timeout" hibát okoz a cTrader kapcsolaton.
            response = await asyncio.to_thread(
                self.anthropic.messages.create,
                model="claude-opus-4-8",
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

            logger.info(f"🤖 AI Döntés: {decision['action']} (confidence: {decision['confidence']:.2f})")
            logger.info(f"💭 Indoklás: {decision['reasoning']}")

            return decision

        except Exception as e:
            logger.error(f"❌ AI döntés hiba: {e}")
            return {
                'action': 'HOLD',
                'confidence': 0.0,
                'reasoning': f'Error: {e}',
                'stop_loss_pips': 0,
                'take_profit_pips': 0
            }

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

            # Pozíció méret számítása
            volume = self.risk_manager.calculate_position_size(
                account_balance=account_info['balance'],
                entry_price=entry_price,
                stop_loss=stop_loss,
                symbol=symbol
            )

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
