#!/usr/bin/env python3
"""
MCP Server for cTrader API Integration
Model Context Protocol eszközök Claude AI számára
WebSocket + JSON implementáció
"""

import json
import logging
import asyncio
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from websockets.asyncio.client import connect
import uuid

# Logging konfiguráció
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CTraderMCPServer:
    """
    MCP Server a cTrader API-hoz (WebSocket + JSON)

    Biztosítja a következő eszközöket:
    - get_market_data: Aktuális piaci árak
    - get_positions: Nyitott pozíciók listája
    - place_order: Piaci megbízás leadása
    - get_candles: Történeti gyertyák
    - get_account_info: Számla információk
    """

    # cTrader API endpoints
    DEMO_HOST = "wss://demo.ctraderapi.com:5036"
    LIVE_HOST = "wss://live.ctraderapi.com:5036"

    # Payload Types (ProtoOA message types)
    PROTO_OA_APPLICATION_AUTH_REQ = 2100
    PROTO_OA_APPLICATION_AUTH_RES = 2101
    PROTO_OA_ACCOUNT_AUTH_REQ = 2102
    PROTO_OA_ACCOUNT_AUTH_RES = 2103
    PROTO_OA_SYMBOL_BY_ID_REQ = 2116
    PROTO_OA_SYMBOL_BY_ID_RES = 2117
    PROTO_OA_SYMBOLS_LIST_REQ = 2114
    PROTO_OA_SYMBOLS_LIST_RES = 2115
    PROTO_OA_SUBSCRIBE_SPOTS_REQ = 2127
    PROTO_OA_SUBSCRIBE_SPOTS_RES = 2128
    PROTO_OA_SPOT_EVENT = 2131
    PROTO_OA_GET_TRENDBARS_REQ = 2137
    PROTO_OA_GET_TRENDBARS_RES = 2138
    PROTO_OA_NEW_ORDER_REQ = 2106
    PROTO_OA_EXECUTION_EVENT = 2126
    PROTO_OA_RECONCILE_REQ = 2124
    PROTO_OA_RECONCILE_RES = 2125
    PROTO_OA_TRADER_REQ = 2121
    PROTO_OA_TRADER_RES = 2122
    PROTO_OA_ERROR_RES = 2142

    def __init__(self, credentials_path: str = "credentials.json"):
        """
        Inicializálás

        Args:
            credentials_path: credentials.json fájl elérési útja
        """
        self.credentials_path = credentials_path
        self.ws = None
        self.connected = False
        self.authenticated = False

        # Credentials
        self.client_id: Optional[str] = None
        self.client_secret: Optional[str] = None
        self.access_token: Optional[str] = None
        self.account_id: Optional[int] = None
        self.is_live: bool = False

        # Cache
        self.symbols_cache: Dict[str, Dict] = {}
        self.symbol_details_cache: Dict[int, Dict] = {}
        self.spot_data_cache: Dict[int, Dict] = {}
        # Melyik symbol_id-kre van már élő spot feliratkozásunk ezen a
        # kapcsolaton - ha nem követnénk, minden get_market_data hívás
        # (pl. minden dashboard poll) újra feliratkozna, feleslegesen
        # terhelve a cTrader API-t (és minden alkalommal új tickre várva).
        self.subscribed_symbol_ids: set = set()

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

            self.client_id = credentials['clientId']
            self.client_secret = credentials['clientSecret']
            self.access_token = credentials['accessToken']
            self.account_id = int(credentials['accountId'])
            self.is_live = credentials.get('isLive', False)

            logger.info(f"✅ Credentials betöltve (Account: {self.account_id})")
            return credentials

        except Exception as e:
            logger.error(f"❌ Credentials betöltési hiba: {e}")
            raise

    async def connect(self):
        """Csatlakozás a cTrader API-hoz"""
        try:
            # Credentials betöltése
            self.load_credentials()

            # WebSocket host kiválasztása
            host = self.LIVE_HOST if self.is_live else self.DEMO_HOST
            logger.info(f"🔌 Csatlakozás: {host}")

            # WebSocket kapcsolat
            self.ws = await connect(host)
            self.connected = True
            logger.info("✅ WebSocket kapcsolat létrejött")

            # Application authentication
            await self._app_auth()

            # Account authentication
            await self._account_auth()

            self.authenticated = True
            logger.info("✅ Teljes authentikáció kész")

        except Exception as e:
            logger.error(f"❌ Csatlakozási hiba: {e}")
            self.connected = False
            self.authenticated = False
            raise

    async def close(self):
        """WebSocket kapcsolat lezárása (kötelező minden kérés után, erőforrás-szivárgás elkerülésére)"""
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
        self.connected = False
        self.authenticated = False
        # Új kapcsolaton a korábbi feliratkozások nem élnek tovább.
        self.subscribed_symbol_ids.clear()

    async def _app_auth(self):
        """Application authentication (payloadType 2100)"""
        msg = {
            'clientMsgId': str(uuid.uuid4()),
            'payloadType': self.PROTO_OA_APPLICATION_AUTH_REQ,
            'payload': {
                'clientId': self.client_id,
                'clientSecret': self.client_secret
            }
        }

        logger.info("🔐 Application auth kérés...")
        await self.ws.send(json.dumps(msg))

        response = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=15))
        if response['payloadType'] != self.PROTO_OA_APPLICATION_AUTH_RES:
            raise Exception(f"Application auth hiba: {response}")

        logger.info("✅ Application auth sikeres")

    async def _account_auth(self):
        """Account authentication (payloadType 2102)"""
        msg = {
            'clientMsgId': str(uuid.uuid4()),
            'payloadType': self.PROTO_OA_ACCOUNT_AUTH_REQ,
            'payload': {
                'ctidTraderAccountId': self.account_id,
                'accessToken': self.access_token
            }
        }

        logger.info("🔐 Account auth kérés...")
        await self.ws.send(json.dumps(msg))

        response = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=15))
        if response['payloadType'] != self.PROTO_OA_ACCOUNT_AUTH_RES:
            raise Exception(f"Account auth hiba: {response}")

        logger.info("✅ Account auth sikeres")

    async def _send_request(self, payload_type: int, payload: Dict) -> Dict:
        """
        Általános kérés küldése és válasz fogadása

        Args:
            payload_type: ProtoOA message type
            payload: Üzenet payload

        Returns:
            Dict: Válasz payload
        """
        if not self.authenticated:
            raise Exception("Nincs authentikálva!")

        client_msg_id = str(uuid.uuid4())
        msg = {
            'clientMsgId': client_msg_id,
            'payloadType': payload_type,
            'payload': payload
        }

        await self.ws.send(json.dumps(msg))

        # A socketen aszinkron push üzenetek (pl. spot event) is érkezhetnek
        # a válaszunk előtt, ezért a clientMsgId alapján válogatjuk ki a miénket,
        # a köztes push üzeneteket pedig cache-eljük/eldobjuk, nem hibaként kezeljük.
        loop = asyncio.get_event_loop()
        deadline = loop.time() + 20
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError(f"Nem érkezett válasz (payloadType={payload_type}) időben")

            raw = await asyncio.wait_for(self.ws.recv(), timeout=remaining)
            response = json.loads(raw)

            if response.get('clientMsgId') == client_msg_id:
                return response

            # Nem a mi válaszunk - ha spot event, gyorsítótárazzuk, egyébként eldobjuk
            self._cache_pushed_message(response)

    def _cache_pushed_message(self, message: Dict) -> None:
        """Aszinkron (nem kért) szerver üzenetek cache-elése, pl. spot event"""
        if message.get('payloadType') == self.PROTO_OA_SPOT_EVENT:
            payload = message.get('payload', {})
            symbol_id = payload.get('symbolId')
            if symbol_id is not None:
                self.spot_data_cache[symbol_id] = payload

    async def get_symbols_list(self) -> List[Dict]:
        """
        Összes elérhető szimbólum lekérése

        Returns:
            List[Dict]: Szimbólumok listája
        """
        try:
            response = await self._send_request(
                self.PROTO_OA_SYMBOLS_LIST_REQ,
                {'ctidTraderAccountId': self.account_id}
            )

            if response['payloadType'] != self.PROTO_OA_SYMBOLS_LIST_RES:
                raise Exception(f"Symbols list hiba: {response}")

            symbols = response['payload'].get('symbol', [])

            # Cache-elés
            for symbol in symbols:
                symbol_name = symbol.get('symbolName')
                if symbol_name:
                    self.symbols_cache[symbol_name] = symbol

            logger.info(f"📊 {len(symbols)} szimbólum betöltve")
            return symbols

        except Exception as e:
            logger.error(f"❌ Symbols list hiba: {e}")
            # Fontos: TOVÁBBDOBJUK a hibát, nem nyelhetjük el üres listával -
            # a hívók (pl. a megosztott admin kapcsolat run_shared/
            # _run_with_shared_server retry-logikája, vagy a bot saját
            # kapcsolat-hiba felismerése) csak akkor tudják érzékelni és
            # újracsatlakoztatni az elszállt kapcsolatot, ha a kivétel
            # valóban felmegy hozzájuk. Ha itt "return []"-t adnánk vissza,
            # a hívó azt hinné, minden rendben, csak nincs adat - és egy
            # halott kapcsolat örökre halott maradna (ez okozta, hogy
            # újraindítás/leállítás után nem jöttek vissza a pozíciók).
            raise

    async def get_symbol_id(self, symbol_name: str) -> Optional[int]:
        """
        Szimbólum ID lekérése név alapján

        Args:
            symbol_name: Szimbólum neve (pl. XAUUSD)

        Returns:
            int: Symbol ID vagy None
        """
        # Cache ellenőrzés
        if symbol_name in self.symbols_cache:
            return self.symbols_cache[symbol_name].get('symbolId')

        # Cache frissítés
        await self.get_symbols_list()

        return self.symbols_cache.get(symbol_name, {}).get('symbolId')

    async def get_symbol_details(self, symbol_id: int) -> Dict[str, Any]:
        """
        Szimbólum kereskedési paramétereinek lekérése (min/max/step volumen),
        cache-elve - ezek nélkül a megbízás könnyen TRADING_BAD_VOLUME /
        TRADING_BAD_STOPS hibával elutasításra kerül, mert minden szimbólumnak
        más a megengedett volumen lépésköze/tartománya.
        """
        cached = self.symbol_details_cache.get(symbol_id)
        if cached:
            return cached

        response = await self._send_request(
            self.PROTO_OA_SYMBOL_BY_ID_REQ,
            {
                'ctidTraderAccountId': self.account_id,
                'symbolId': [symbol_id]
            }
        )

        if response['payloadType'] != self.PROTO_OA_SYMBOL_BY_ID_RES:
            raise Exception(f"Symbol details hiba: {response}")

        details_list = response['payload'].get('symbol', [])
        if not details_list:
            raise Exception(f"Symbol details nem található (symbolId={symbol_id})")

        details = details_list[0]
        self.symbol_details_cache[symbol_id] = details
        return details

    async def get_market_data(self, symbol: str = "XAUUSD") -> Dict[str, Any]:
        """
        Aktuális piaci adatok lekérése

        Args:
            symbol: Trading szimbólum (pl. XAUUSD, EURUSD)

        Returns:
            Dict: Piaci adatok (bid, ask, spread, timestamp)
        """
        try:
            if not self.authenticated:
                await self.connect()

            # Symbol ID lekérése
            symbol_id = await self.get_symbol_id(symbol)
            if not symbol_id:
                raise ValueError(f"Szimbólum nem található: {symbol}")

            # Spot subscription (a válasz csak a feliratkozást nyugtázza, az árat
            # egy külön, aszinkron spot event tartalmazza). Csak akkor
            # küldjük el, ha ezen a kapcsolaton még nem iratkoztunk fel erre a
            # symbol_id-ra - különben minden hívás (pl. minden dashboard poll)
            # újra feliratkozna, feleslegesen terhelve a cTrader API-t.
            if symbol_id not in self.subscribed_symbol_ids:
                response = await self._send_request(
                    self.PROTO_OA_SUBSCRIBE_SPOTS_REQ,
                    {
                        'ctidTraderAccountId': self.account_id,
                        'symbolId': [symbol_id]
                    }
                )

                already_subscribed = (
                    response['payloadType'] == self.PROTO_OA_ERROR_RES
                    and response.get('payload', {}).get('errorCode') == 'ALREADY_SUBSCRIBED'
                )
                if response['payloadType'] != self.PROTO_OA_SUBSCRIBE_SPOTS_RES and not already_subscribed:
                    raise Exception(f"Spot subscription hiba: {response}")
                # ALREADY_SUBSCRIBED nem hiba: pl. egy korábbi kapcsolat már
                # feliratkozott, de a saját `subscribed_symbol_ids` állapotunk
                # (újracsatlakozás miatt) nem tudott róla - egyszerűen
                # nyugtázzuk feliratkozottnak, folytatjuk a cache-ből.
                self.subscribed_symbol_ids.add(symbol_id)

            # Spot event várakozás (timeout, ha nem jön tick időben). A cache-ben
            # már benne lehet, ha _send_request közben kaptuk meg push-ként.
            deadline = asyncio.get_event_loop().time() + 15
            payload = self.spot_data_cache.get(symbol_id)
            while not payload and asyncio.get_event_loop().time() < deadline:
                raw = await asyncio.wait_for(
                    self.ws.recv(),
                    timeout=max(deadline - asyncio.get_event_loop().time(), 0.1)
                )
                event = json.loads(raw)
                self._cache_pushed_message(event)
                payload = self.spot_data_cache.get(symbol_id)

            if payload:
                raw_bid = payload.get('bid')
                raw_ask = payload.get('ask')
                if raw_bid or raw_ask:
                    bid = (raw_bid or raw_ask) / 100000  # Normalize
                    ask = (raw_ask or raw_bid) / 100000

                    result = {
                        'symbol': symbol,
                        'bid': bid,
                        'ask': ask,
                        'spread': ask - bid,
                        'timestamp': datetime.now().isoformat()
                    }

                    logger.info(f"📊 {symbol}: Bid={bid:.5f}, Ask={ask:.5f}")
                    return result

            # Fallback: dummy data ha nincs tick
            return {
                'symbol': symbol,
                'bid': 2650.50,
                'ask': 2650.80,
                'spread': 0.30,
                'timestamp': datetime.now().isoformat(),
                'note': 'Demo data - no real tick received'
            }

        except Exception as e:
            logger.error(f"❌ Market data hiba: {e}")
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
            if not self.authenticated:
                await self.connect()

            response = await self._send_request(
                self.PROTO_OA_RECONCILE_REQ,
                {'ctidTraderAccountId': self.account_id}
            )

            if response['payloadType'] != self.PROTO_OA_RECONCILE_RES:
                raise Exception(f"Reconcile hiba: {response}")

            positions_data = response['payload'].get('position', [])
            positions = []

            for pos in positions_data:
                trade_data = pos.get('tradeData', {})
                trade_side = trade_data.get('tradeSide')
                positions.append({
                    'position_id': pos.get('positionId'),
                    'symbol_id': trade_data.get('symbolId'),
                    'volume': trade_data.get('volume'),
                    'side': 'BUY' if trade_side in ('BUY', 1) else 'SELL',
                    'entry_price': pos.get('price', 0),
                    'current_price': pos.get('price', 0),
                    'swap': pos.get('swap', 0) / 100,
                    'commission': pos.get('commission', 0) / 100,
                    'profit': 0,  # a nyitott pozíció valós P&L-jéhez élő árfolyam kell (get_market_data)
                    'timestamp': datetime.fromtimestamp(
                        trade_data.get('openTimestamp', 0) / 1000
                    ).isoformat() if trade_data.get('openTimestamp') else None
                })

            logger.info(f"📈 Nyitott pozíciók: {len(positions)}")
            return positions

        except Exception as e:
            logger.error(f"❌ Pozíciók lekérési hiba: {e}")
            # Lásd get_symbols_list komment - itt sem nyelhetjük el a hibát,
            # különben a hívó reconnect-logikája sosem aktiválódik.
            raise

    async def place_order(
        self,
        symbol: str,
        side: str,
        lots: float = 0.01,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Piaci megbízás leadása (valós leküldés a cTrader szerverre)

        Args:
            symbol: Trading szimbólum (pl. XAUUSD)
            side: 'BUY' vagy 'SELL'
            lots: Volumen lotban (0.01 = mikro lot, minimum általában 0.01)
            stop_loss: Stop loss ár (opcionális)
            take_profit: Take profit ár (opcionális)

        Returns:
            Dict: Megbízás eredménye
        """
        try:
            if not self.authenticated:
                await self.connect()

            if self.is_live:
                raise PermissionError(
                    "Élő (live) számlára automatikus megbízás küldése le van tiltva biztonsági okból. "
                    "Csak demo számlán engedélyezett."
                )

            # Symbol ID
            symbol_id = await self.get_symbol_id(symbol)
            if not symbol_id:
                raise ValueError(f"Szimbólum nem található: {symbol}")

            # cTrader API: volume = lot * 10,000,000 (centiunit)
            volume = int(round(lots * 10_000_000))

            # A symbol saját min/max/step volumen korlátait a cTrader szabja meg,
            # nem az általunk feltételezett 0.01 lot - ennek hiánya
            # TRADING_BAD_VOLUME hibát okoz, ha a kockázatmenedzsment által
            # kalkulált volumen nem esik a megengedett tartományba/lépésközbe.
            symbol_digits = None
            try:
                symbol_details = await self.get_symbol_details(symbol_id)
                min_volume = symbol_details.get('minVolume', volume)
                max_volume = symbol_details.get('maxVolume', volume)
                step_volume = symbol_details.get('stepVolume', 1) or 1
                symbol_digits = symbol_details.get('digits')

                volume = max(min_volume, min(volume, max_volume))
                # Kerekítés a legközelebbi lépésközre, majd újra a határok közé
                # szorítás - a kerekítés (főleg ha max-min nem osztható step-pel,
                # vagy .5-nél lefelé kerekít a Python banker's rounding miatt)
                # a tartományon kívülre vagy nem egész értékre vihet.
                volume = min_volume + round((volume - min_volume) / step_volume) * step_volume
                volume = int(max(min_volume, min(volume, max_volume)))
            except Exception as detail_error:
                logger.warning(f"⚠️ Symbol details lekérési hiba ({symbol}), eredeti volumen marad: {detail_error}")

            # Order payload
            order_payload = {
                'ctidTraderAccountId': self.account_id,
                'symbolId': symbol_id,
                'orderType': 'MARKET',
                'tradeSide': side.upper(),
                'volume': volume,
                'timeInForce': 'IMMEDIATE_OR_CANCEL',
                'label': 'AI Trading Advisor',
                'comment': 'AI Trading Advisor'
            }

            # A stopLoss/takeProfit mezők a ProtoOANewOrderReq-ben 'double' típusúak,
            # tehát a valós ár értékét várják közvetlenül (pl. 1.14489), NEM az
            # 1e5-tel skálázott egész számot, ahogy a spot ár/gyertya mezőknél -
            # a korábbi int(x*100000) skálázás emiatt okozott TRADING_BAD_STOPS hibát.
            # A szimbólum saját 'digits' értékére kell kerekíteni, különben
            # a lebegőpontos műveletek extra tizedesjegyet hoznak be (pl. USDJPY
            # 3 digit helyett 162.60399999999998), ami INVALID_REQUEST hibát okoz.
            digits = symbol_digits if symbol_digits is not None else 5
            if stop_loss:
                order_payload['stopLoss'] = round(float(stop_loss), digits)
            if take_profit:
                order_payload['takeProfit'] = round(float(take_profit), digits)

            response = await self._send_request(
                self.PROTO_OA_NEW_ORDER_REQ,
                order_payload
            )

            payload = response.get('payload', {})

            # A megbízás küldésére a válasz egy PROTO_OA_EXECUTION_EVENT (2126),
            # NEM a kérés típusának visszhangja - executionType/orderStatus dönti el a sikert.
            # ACCEPTED/FILLED/PARTIAL_FILL = siker, REJECTED/CANCELLED/EXPIRED = hiba.
            execution_type = payload.get('executionType')
            EXECUTION_STATUS_LABELS = {
                2: 'accepted',       # ORDER_ACCEPTED - elfogadva, a tényleges fill egy külön (később érkező) event
                3: 'filled',         # ORDER_FILLED
                11: 'partial_fill',  # ORDER_PARTIAL_FILL
            }
            REJECTION_EXECUTION_TYPES = {
                5: 'cancelled',        # ORDER_CANCELLED
                6: 'expired',          # ORDER_EXPIRED
                7: 'rejected',         # ORDER_REJECTED
                8: 'cancel_rejected',  # ORDER_CANCEL_REJECTED
            }

            if (response['payloadType'] == self.PROTO_OA_EXECUTION_EVENT
                    and execution_type in EXECUTION_STATUS_LABELS
                    and 'order' in payload):
                result = {
                    'success': True,
                    'status': EXECUTION_STATUS_LABELS[execution_type],
                    'order_id': payload.get('order', {}).get('orderId'),
                    'position_id': payload.get('position', {}).get('positionId'),
                    'symbol': symbol,
                    'side': side,
                    'volume': lots,
                    'timestamp': datetime.now().isoformat()
                }

                logger.info(f"✅ Megbízás {result['status']}: {symbol} {side} {lots:.2f} lot (pozíció: {result['position_id']})")
                return result
            elif execution_type in REJECTION_EXECUTION_TYPES:
                raise Exception(
                    f"Megbízás elutasítva ({REJECTION_EXECUTION_TYPES[execution_type]}): "
                    f"{payload.get('errorCode', payload.get('description', 'ismeretlen hiba'))}"
                )
            else:
                raise Exception(f"Execution hiba: {payload.get('errorCode', payload.get('description', response))}")

        except Exception as e:
            logger.error(f"❌ Place order hiba: {e}")
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
            if not self.authenticated:
                await self.connect()

            # Symbol ID
            symbol_id = await self.get_symbol_id(symbol)
            if not symbol_id:
                raise ValueError(f"Szimbólum nem található: {symbol}")

            # Timeframe map (ProtoOATrendbarPeriod numerikus enum értékei)
            timeframe_map = {
                'M1': 1,
                'M2': 2,
                'M3': 3,
                'M4': 4,
                'M5': 5,
                'M10': 6,
                'M15': 7,
                'M30': 8,
                'H1': 9,
                'H4': 10,
                'H12': 11,
                'D1': 12,
                'W1': 13,
                'MN1': 14
            }

            # Time range
            to_timestamp = int(datetime.now().timestamp() * 1000)
            from_timestamp = int((datetime.now() - timedelta(days=7)).timestamp() * 1000)

            response = await self._send_request(
                self.PROTO_OA_GET_TRENDBARS_REQ,
                {
                    'ctidTraderAccountId': self.account_id,
                    'symbolId': symbol_id,
                    'period': timeframe_map.get(timeframe, 5),
                    'fromTimestamp': from_timestamp,
                    'toTimestamp': to_timestamp,
                    'count': count
                }
            )

            if response['payloadType'] != self.PROTO_OA_GET_TRENDBARS_RES:
                raise Exception(f"Trendbars hiba: {response}")

            trendbars = response['payload'].get('trendbar', [])
            candles = []

            for bar in trendbars:
                # A trendbar 'low' + delta kódolt (deltaOpen/deltaHigh/deltaClose
                # az alacsonyhoz képesti eltérés), nem közvetlen OHLC mezők
                low = bar.get('low', 0)
                candles.append({
                    'timestamp': datetime.utcfromtimestamp(
                        bar.get('utcTimestampInMinutes', 0) * 60
                    ).isoformat(),
                    'open': (low + bar.get('deltaOpen', 0)) / 100000,
                    'high': (low + bar.get('deltaHigh', 0)) / 100000,
                    'low': low / 100000,
                    'close': (low + bar.get('deltaClose', 0)) / 100000,
                    'volume': bar.get('volume', 0)
                })

            logger.info(f"📊 {len(candles)} gyertya ({symbol} {timeframe})")
            return candles[-count:] if len(candles) > count else candles

        except Exception as e:
            logger.error(f"❌ Candles hiba: {e}")
            return []

    async def get_account_info(self) -> Dict[str, Any]:
        """
        Számla információk lekérése

        Returns:
            Dict: Számla adatok
        """
        try:
            if not self.authenticated:
                await self.connect()

            response = await self._send_request(
                self.PROTO_OA_TRADER_REQ,
                {'ctidTraderAccountId': self.account_id}
            )

            if response['payloadType'] == self.PROTO_OA_TRADER_RES:
                trader = response['payload'].get('trader', {})

                # ProtoOATrader mezői: 'balance' + 'moneyDigits' (a balance skálázási
                # faktora, tizedesjegyek száma - NEM az equity/margin számításának
                # bemenete, ahogy korábban feltételeztük). marginUsed/freeMargin
                # mezők nem léteznek a ProtoOATrader-ben, a valós szabad fedezet
                # a nyitott pozíciók (get_positions) alapján számítható, itt nem
                # áll rendelkezésre közvetlenül.
                money_digits = trader.get('moneyDigits', 2)
                scale = 10 ** money_digits
                balance = trader.get('balance', 0) / scale

                account_info = {
                    'account_id': self.account_id,
                    'balance': balance,
                    'currency': 'USD',
                    'timestamp': datetime.now().isoformat()
                }

                logger.info(f"💰 Balance: ${account_info['balance']:.2f}")
                return account_info
            else:
                raise Exception(f"Trader info hiba: {response}")

        except Exception as e:
            logger.error(f"❌ Account info hiba: {e}")
            return {}

            self.connected = False
            self.authenticated = False
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
        "description": "Get trading account information (balance) - equity/margin are not exposed by the ProtoOATrader message",
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

            # Szimbólumok lista
            symbols = await server.get_symbols_list()
            print(f"\n📊 Elérhető szimbólumok: {len(symbols)}")

            # Piaci adatok
            market_data = await server.get_market_data("XAUUSD")
            print(f"\n💰 Market Data: {market_data}")

            # Account info
            account_info = await server.get_account_info()
            print(f"\n💼 Account: {account_info}")

            # Pozíciók
            positions = await server.get_positions()
            print(f"\n📈 Positions: {positions}")

        except Exception as e:
            print(f"\n❌ Hiba: {e}")
        finally:
            await server.close()

    # Futtatás
    print("=" * 60)
    print("🤖 MCP Server Test (WebSocket + JSON)")
    print("=" * 60)
    asyncio.run(test_mcp())
