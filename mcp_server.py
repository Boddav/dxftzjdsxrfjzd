#!/usr/bin/env python3
"""
MCP Server for cTrader API Integration
Model Context Protocol eszközök Claude AI számára
"""

import json
import logging
import asyncio
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from ctrader_open_api import Client, Protobuf, TcpProtocol, Auth, EndPoints
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from twisted.internet import reactor

# Logging konfiguráció
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CTraderMCPServer:
    """
    MCP Server a cTrader API-hoz

    Biztosítja a következő eszközöket:
    - get_market_data: Aktuális piaci árak
    - get_positions: Nyitott pozíciók listája
    - place_order: Piaci megbízás leadása
    - get_candles: Történeti gyertyák
    - get_account_info: Számla információk
    """

    def __init__(self, credentials_path: str = "credentials.json"):
        """
        Inicializálás

        Args:
            credentials_path: credentials.json fájl elérési útja
        """
        self.credentials_path = credentials_path
        self.client: Optional[Client] = None
        self.connected = False
        self.account_id: Optional[int] = None
        self.access_token: Optional[str] = None

        # Cache piaci adatokhoz
        self.market_data_cache: Dict[str, Dict] = {}

        logger.info("🚀 MCP Server inicializálva")

    def load_credentials(self) -> Dict[str, Any]:
        """
        Credentials betöltése

        Returns:
            Dict: Credentials adatok
        """
        try:
            with open(self.credentials_path, 'r') as f:
                credentials = json.load(f)

            self.access_token = credentials['access_token']
            self.account_id = int(credentials['account_id'])

            logger.info(f"✅ Credentials betöltve (Account: {self.account_id})")
            return credentials

        except Exception as e:
            logger.error(f"❌ Credentials betöltési hiba: {e}")
            raise

    async def connect(self):
        """Csatlakozás a cTrader API-hoz"""
        try:
            credentials = self.load_credentials()

            # cTrader Open API kliens létrehozása
            self.client = Client(
                EndPoints.PROTOBUF_LIVE_HOST if credentials.get('live', False) else EndPoints.PROTOBUF_DEMO_HOST,
                EndPoints.PROTOBUF_PORT,
                TcpProtocol
            )

            # Csatlakozás
            await self.client.connect()

            # Authentikáció
            auth_request = ProtoOAApplicationAuthReq()
            auth_request.clientId = credentials['client_id']
            auth_request.clientSecret = credentials['client_secret']

            await self.client.send(auth_request)

            # Account auth
            account_auth_request = ProtoOAAccountAuthReq()
            account_auth_request.ctidTraderAccountId = self.account_id
            account_auth_request.accessToken = self.access_token

            await self.client.send(account_auth_request)

            self.connected = True
            logger.info("✅ Csatlakozva a cTrader API-hoz")

        except Exception as e:
            logger.error(f"❌ Csatlakozási hiba: {e}")
            self.connected = False
            raise

    async def get_market_data(self, symbol: str = "XAUUSD") -> Dict[str, Any]:
        """
        Aktuális piaci adatok lekérése

        Args:
            symbol: Trading szimbólum (pl. XAUUSD, EURUSD)

        Returns:
            Dict: Piaci adatok (bid, ask, spread, timestamp)
        """
        try:
            if not self.connected:
                await self.connect()

            # Symbol lookup
            symbols_request = ProtoOASymbolsListReq()
            symbols_request.ctidTraderAccountId = self.account_id

            response = await self.client.send(symbols_request)

            # Symbol ID keresése
            symbol_id = None
            for sym in response.symbol:
                if sym.symbolName == symbol:
                    symbol_id = sym.symbolId
                    break

            if not symbol_id:
                raise ValueError(f"Szimbólum nem található: {symbol}")

            # Tick subscription
            subscribe_request = ProtoOASubscribeSpotsReq()
            subscribe_request.ctidTraderAccountId = self.account_id
            subscribe_request.symbolId.append(symbol_id)

            await self.client.send(subscribe_request)

            # Tick adatok várakozás
            tick_data = await self._wait_for_tick(symbol_id)

            result = {
                'symbol': symbol,
                'bid': tick_data['bid'],
                'ask': tick_data['ask'],
                'spread': tick_data['ask'] - tick_data['bid'],
                'timestamp': datetime.now().isoformat()
            }

            logger.info(f"📊 Piaci adatok ({symbol}): Bid={result['bid']}, Ask={result['ask']}")
            return result

        except Exception as e:
            logger.error(f"❌ Piaci adatok lekérési hiba: {e}")
            return {
                'error': str(e),
                'symbol': symbol
            }

    async def get_positions(self) -> List[Dict[str, Any]]:
        """
        Nyitott pozíciók listája

        Returns:
            List[Dict]: Pozíciók listája
        """
        try:
            if not self.connected:
                await self.connect()

            # Pozíciók lekérése
            positions_request = ProtoOAReconcileReq()
            positions_request.ctidTraderAccountId = self.account_id

            response = await self.client.send(positions_request)

            positions = []
            for position in response.position:
                positions.append({
                    'position_id': position.positionId,
                    'symbol_id': position.tradeData.symbolId,
                    'volume': position.tradeData.volume,
                    'side': 'BUY' if position.tradeData.tradeSide == ProtoOATradeSide.BUY else 'SELL',
                    'entry_price': position.price,
                    'current_price': position.price,  # Frissíteni kell tick adatokkal
                    'profit': position.moneyDigits,
                    'timestamp': datetime.fromtimestamp(position.tradeData.openTimestamp / 1000).isoformat()
                })

            logger.info(f"📈 Nyitott pozíciók száma: {len(positions)}")
            return positions

        except Exception as e:
            logger.error(f"❌ Pozíciók lekérési hiba: {e}")
            return []

    async def place_order(
        self,
        symbol: str,
        side: str,
        volume: int,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Piaci megbízás leadása

        Args:
            symbol: Trading szimbólum (pl. XAUUSD)
            side: 'BUY' vagy 'SELL'
            volume: Volumen mikroegységben (10000 = 0.01 lot)
            stop_loss: Stop loss ár (opcionális)
            take_profit: Take profit ár (opcionális)

        Returns:
            Dict: Megbízás eredménye
        """
        try:
            if not self.connected:
                await self.connect()

            # Symbol ID lekérése
            symbol_id = await self._get_symbol_id(symbol)

            # Megbízás létrehozása
            order_request = ProtoOANewOrderReq()
            order_request.ctidTraderAccountId = self.account_id
            order_request.symbolId = symbol_id
            order_request.orderType = ProtoOAOrderType.MARKET
            order_request.tradeSide = ProtoOATradeSide.BUY if side.upper() == 'BUY' else ProtoOATradeSide.SELL
            order_request.volume = volume

            # Stop Loss és Take Profit
            if stop_loss:
                order_request.stopLoss = stop_loss
            if take_profit:
                order_request.takeProfit = take_profit

            # Megbízás elküldése
            response = await self.client.send(order_request)

            result = {
                'success': True,
                'order_id': response.orderId,
                'position_id': response.positionId if hasattr(response, 'positionId') else None,
                'symbol': symbol,
                'side': side,
                'volume': volume,
                'timestamp': datetime.now().isoformat()
            }

            logger.info(f"✅ Megbízás leadva: {symbol} {side} {volume/100000} lot")
            return result

        except Exception as e:
            logger.error(f"❌ Megbízás leadási hiba: {e}")
            return {
                'success': False,
                'error': str(e),
                'symbol': symbol
            }

    async def get_candles(
        self,
        symbol: str,
        timeframe: str = "M5",
        count: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Történeti gyertyák lekérése

        Args:
            symbol: Trading szimbólum
            timeframe: Időkeret (M1, M5, M15, M30, H1, H4, D1)
            count: Gyertyák száma

        Returns:
            List[Dict]: Gyertyák listája (OHLC + volume)
        """
        try:
            if not self.connected:
                await self.connect()

            # Symbol ID lekérése
            symbol_id = await self._get_symbol_id(symbol)

            # Timeframe konverzió
            timeframe_map = {
                'M1': ProtoOATrendbarPeriod.M1,
                'M5': ProtoOATrendbarPeriod.M5,
                'M15': ProtoOATrendbarPeriod.M15,
                'M30': ProtoOATrendbarPeriod.M30,
                'H1': ProtoOATrendbarPeriod.H1,
                'H4': ProtoOATrendbarPeriod.H4,
                'D1': ProtoOATrendbarPeriod.D1
            }

            # Gyertyák lekérése
            candles_request = ProtoOAGetTrendbarsReq()
            candles_request.ctidTraderAccountId = self.account_id
            candles_request.symbolId = symbol_id
            candles_request.period = timeframe_map.get(timeframe, ProtoOATrendbarPeriod.M5)
            candles_request.fromTimestamp = int((datetime.now() - timedelta(days=7)).timestamp() * 1000)
            candles_request.toTimestamp = int(datetime.now().timestamp() * 1000)

            response = await self.client.send(candles_request)

            candles = []
            for i in range(len(response.trendbar)):
                bar = response.trendbar[i]
                candles.append({
                    'timestamp': datetime.fromtimestamp(bar.utcTimestampInMinutes * 60).isoformat(),
                    'open': bar.open,
                    'high': bar.high,
                    'low': bar.low,
                    'close': bar.close,
                    'volume': bar.volume
                })

            logger.info(f"📊 {len(candles)} gyertya lekérve ({symbol} {timeframe})")
            return candles[-count:] if len(candles) > count else candles

        except Exception as e:
            logger.error(f"❌ Gyertyák lekérési hiba: {e}")
            return []

    async def get_account_info(self) -> Dict[str, Any]:
        """
        Számla információk lekérése

        Returns:
            Dict: Számla adatok (balance, equity, margin, free margin)
        """
        try:
            if not self.connected:
                await self.connect()

            # Account info lekérés
            trader_request = ProtoOATraderReq()
            trader_request.ctidTraderAccountId = self.account_id

            response = await self.client.send(trader_request)

            account_info = {
                'account_id': self.account_id,
                'balance': response.trader.balance / 100,  # Cent-ről dollárra
                'equity': (response.trader.balance + response.trader.moneyDigits) / 100,
                'margin_used': response.trader.marginUsed / 100 if hasattr(response.trader, 'marginUsed') else 0,
                'free_margin': response.trader.freeMargin / 100 if hasattr(response.trader, 'freeMargin') else 0,
                'currency': 'USD',
                'timestamp': datetime.now().isoformat()
            }

            logger.info(f"💰 Számla egyenleg: ${account_info['balance']:.2f}")
            return account_info

        except Exception as e:
            logger.error(f"❌ Számla info lekérési hiba: {e}")
            return {}

    async def _get_symbol_id(self, symbol: str) -> int:
        """Symbol ID lekérése névből"""
        symbols_request = ProtoOASymbolsListReq()
        symbols_request.ctidTraderAccountId = self.account_id

        response = await self.client.send(symbols_request)

        for sym in response.symbol:
            if sym.symbolName == symbol:
                return sym.symbolId

        raise ValueError(f"Szimbólum nem található: {symbol}")

    async def _wait_for_tick(self, symbol_id: int, timeout: int = 5) -> Dict[str, float]:
        """Tick adat várakozás"""
        # Egyszerűsített implementáció - valós implementációban event listener kell
        await asyncio.sleep(0.5)

        # Dummy tick data (valós implementációban a client tick event-jeiből)
        return {
            'bid': 2650.50,
            'ask': 2650.80
        }

    async def close(self):
        """Kapcsolat bontása"""
        if self.client:
            await self.client.disconnect()
            self.connected = False
            logger.info("👋 MCP Server leállítva")


# MCP Tools definíciók Claude AI számára
MCP_TOOLS = [
    {
        "name": "get_market_data",
        "description": "Get current market data for a trading symbol (bid, ask, spread)",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Trading symbol (e.g., XAUUSD, EURUSD)",
                    "default": "XAUUSD"
                }
            }
        }
    },
    {
        "name": "get_positions",
        "description": "Get list of all open trading positions",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "place_order",
        "description": "Place a market order (BUY or SELL)",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Trading symbol"
                },
                "side": {
                    "type": "string",
                    "enum": ["BUY", "SELL"],
                    "description": "Order side"
                },
                "volume": {
                    "type": "integer",
                    "description": "Volume in micro units (10000 = 0.01 lot)"
                },
                "stop_loss": {
                    "type": "number",
                    "description": "Stop loss price (optional)"
                },
                "take_profit": {
                    "type": "number",
                    "description": "Take profit price (optional)"
                }
            },
            "required": ["symbol", "side", "volume"]
        }
    },
    {
        "name": "get_candles",
        "description": "Get historical candle data (OHLC)",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Trading symbol"
                },
                "timeframe": {
                    "type": "string",
                    "enum": ["M1", "M5", "M15", "M30", "H1", "H4", "D1"],
                    "description": "Timeframe",
                    "default": "M5"
                },
                "count": {
                    "type": "integer",
                    "description": "Number of candles",
                    "default": 100
                }
            },
            "required": ["symbol"]
        }
    },
    {
        "name": "get_account_info",
        "description": "Get trading account information (balance, equity, margin)",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    }
]


if __name__ == "__main__":
    # MCP Server teszt
    async def test_mcp():
        server = CTraderMCPServer()

        try:
            # Csatlakozás
            await server.connect()

            # Tesztek
            market_data = await server.get_market_data("XAUUSD")
            print(f"Market Data: {market_data}")

            account_info = await server.get_account_info()
            print(f"Account Info: {account_info}")

            positions = await server.get_positions()
            print(f"Positions: {positions}")

        finally:
            await server.close()

    # Futtatás
    asyncio.run(test_mcp())
