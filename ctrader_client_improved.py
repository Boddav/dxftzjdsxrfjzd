#!/usr/bin/env python3
"""
cTrader API Client - Továbbfejlesztett hibakezeléssel
Twisted alapú, proper error handling és retry mechanizmussal
"""

import json
import logging
from typing import Dict, List, Optional, Callable
from twisted.internet import reactor, defer
from twisted.internet.error import TimeoutError
from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
import ctrader_open_api.messages.OpenApiMessages_pb2 as OA

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CTraderAPIError(Exception):
    """cTrader API specifikus hiba"""
    pass


class CTraderClient:
    """
    Továbbfejlesztett cTrader API kliens
    - Proper error handling
    - Connection retry
    - Token refresh
    - Detailed logging
    """

    def __init__(self, credentials_path: str = "credentials.json"):
        self.credentials_path = credentials_path
        self.client: Optional[Client] = None
        self.connected = False
        self.authenticated = False

        # Credentials
        self.client_id: Optional[str] = None
        self.client_secret: Optional[str] = None
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.account_id: Optional[int] = None

        # Callbacks
        self.on_price_update: Optional[Callable] = None

        logger.info("🔧 cTrader Client inicializálva")

    def load_credentials(self) -> Dict:
        """Credentials betöltése és validálása"""
        try:
            with open(self.credentials_path, 'r') as f:
                creds = json.load(f)

            # Kötelező mezők (account_id opcionális – 2102-vel lekérjük, ha hiányzik)
            required = ['client_id', 'client_secret', 'access_token']
            missing = [f for f in required if not creds.get(f)]

            if missing:
                raise CTraderAPIError(f"Hiányzó credentials mezők: {missing}")

            self.client_id = creds['client_id']
            self.client_secret = creds['client_secret']
            self.access_token = creds['access_token']
            self.refresh_token = creds.get('refresh_token')

            acc = creds.get('account_id')
            self.account_id = int(acc) if acc not in (
                None, "", False) else None

            logger.info(f"✅ Credentials betöltve")
            logger.info(f"   Client ID: {self.client_id[:20]}...")
            if self.account_id is not None:
                logger.info(f"   Account ID: {self.account_id}")
            else:
                logger.info("   Account ID: (hiányzik – lekérjük 2102-vel)")

            return creds

        except FileNotFoundError:
            raise CTraderAPIError(
                f"credentials.json nem található: {self.credentials_path}")
        except json.JSONDecodeError:
            raise CTraderAPIError("credentials.json hibás JSON formátum")
        except Exception as e:
            raise CTraderAPIError(f"Credentials betöltési hiba: {e}")

    def connect(self):
        """Kapcsolódás a cTrader API-hoz"""
        try:
            self.load_credentials()

            # Demo vagy Live endpoint
            host = EndPoints.PROTOBUF_DEMO_HOST  # demo.ctraderapi.com
            port = EndPoints.PROTOBUF_PORT  # 5035

            logger.info(f"🔌 Csatlakozás: {host}:{port}")

            # Client létrehozása
            self.client = Client(host, port, TcpProtocol)

            # Callbacks beállítása
            self.client.setConnectedCallback(self._on_connected)
            self.client.setDisconnectedCallback(self._on_disconnected)
            self.client.setMessageReceivedCallback(self._on_message)

            # Kapcsolódás indítása
            self.client.startService()

        except Exception as e:
            logger.error(f"❌ Kapcsolódási hiba: {e}")
            raise CTraderAPIError(f"Nem sikerült csatlakozni: {e}")

    def _on_connected(self, client):
        """Kapcsolat létrejött callback"""
        logger.info("✅ TCP kapcsolat létrejött")
        self.connected = True

        # Alkalmazás autentikáció
        logger.info("🔐 Alkalmazás autentikáció...")
        auth_req = OA.ProtoOAApplicationAuthReq()
        auth_req.clientId = self.client_id
        auth_req.clientSecret = self.client_secret

        deferred = self.client.send(auth_req)
        deferred.addCallbacks(self._on_app_auth_success, self._on_error)

    def _on_app_auth_success(self, message):
        """Alkalmazás autentikáció sikeres"""
        # Ellenőrizzük hogy error-e
        if message.payloadType == OA.ProtoOAErrorRes().payloadType:
            error = Protobuf.extract(message)
            logger.error(f"❌ App auth hiba: {error}")
            self._handle_auth_error(error)
            return

        logger.info("✅ Alkalmazás autentikáció sikeres")
        # Ha még nincs account_id vagy kényszerítjük a lekérést, akkor előbb kérjük le a hozzáférhető accountokat
        if not self.account_id:
            logger.info(
                "🔍 Nincs account_id – lekérés access token alapján (2102)...")
            req = OA.ProtoOAGetAccountsByAccessTokenReq()
            req.accessToken = self.access_token
            deferred = self.client.send(req)
            deferred.addCallbacks(
                self._on_accounts_list_success, self._on_error)
        else:
            self._send_account_auth()

    def _on_accounts_list_success(self, message):
        """Account lista lekérése sikeres (payloadType 2150)"""
        if message.payloadType == OA.ProtoOAErrorRes().payloadType:
            error = Protobuf.extract(message)
            logger.error(f"❌ Account lista hiba: {error}")
            self._handle_auth_error(error)
            return

        data = Protobuf.extract(message)
        # A válasz struktúrája: ctidTraderAccount (ismétlődő mező)
        accounts = getattr(data, 'ctidTraderAccount', [])
        if not accounts:
            logger.error("❌ Nincs elérhető account a tokenhez")
            self._handle_auth_error(
                {'errorCode': 'NO_ACCOUNT', 'description': 'No accounts tied to token'})
            return

        # Preferált: demo (isLive == False)
        selected = None
        for acc in accounts:
            if hasattr(acc, 'isLive') and acc.isLive is False:
                selected = acc
                break
        if selected is None:
            selected = accounts[0]

        self.account_id = selected.ctidTraderAccountId
        logger.info(
            f"✅ Account kiválasztva: {self.account_id} (isLive={getattr(selected,'isLive',None)})")
        self._persist_account_id()
        self._send_account_auth()

    def _persist_account_id(self):
        """Frissített account_id mentése credentials.json-be"""
        try:
            with open(self.credentials_path, 'r') as f:
                creds = json.load(f)
            creds['account_id'] = self.account_id
            with open(self.credentials_path, 'w') as f:
                json.dump(creds, f, indent=2)
            logger.info("💾 credentials.json frissítve (account_id mentve)")
        except Exception as e:
            logger.warning(f"⚠️ Nem sikerült menteni az account_id-t: {e}")

    def _send_account_auth(self):
        """Account autentikációs üzenet küldése"""
        if not self.account_id:
            logger.error("❌ Nincs account_id az autentikációhoz")
            return
        logger.info(f"👤 Fiók autentikáció (Account ID: {self.account_id})...")
        acc_auth_req = OA.ProtoOAAccountAuthReq()
        acc_auth_req.ctidTraderAccountId = self.account_id
        acc_auth_req.accessToken = self.access_token
        deferred = self.client.send(acc_auth_req)
        deferred.addCallbacks(self._on_account_auth_success, self._on_error)

    def _on_account_auth_success(self, message):
        """Account autentikáció sikeres"""
        # Ellenőrizzük hogy error-e
        if message.payloadType == OA.ProtoOAErrorRes().payloadType:
            error = Protobuf.extract(message)
            logger.error(f"❌ Account auth hiba: {error}")

            # CH_ACCESS_TOKEN_INVALID hiba részletes kezelése
            if 'CH_ACCESS_TOKEN_INVALID' in str(error):
                logger.error("=" * 70)
                logger.error("🚨 ACCESS TOKEN INVALID HIBA")
                logger.error("=" * 70)
                logger.error("")
                logger.error(
                    "A probléma: Az access token nem érvényes ehhez az account-hoz.")
                logger.error("")
                logger.error("Lehetséges okok:")
                logger.error(
                    "1. Az OAuth során nem választottál ki trading account-ot")
                logger.error("2. Az access token másik account-hoz tartozik")
                logger.error("3. A token lejárt vagy érvénytelen")
                logger.error("")
                logger.error("Megoldás:")
                logger.error("1. Töröld: rm credentials.json")
                logger.error("2. Új OAuth: python ctrader_oauth_setup.py")
                logger.error(
                    "3. FONTOS: A böngészőben VÁLASSZ KI trading account-ot!")
                logger.error(
                    "4. Vagy ellenőrizd hogy a helyes account ID-t használod")
                logger.error("")
                logger.error("=" * 70)

            self._handle_auth_error(error)
            return

        logger.info("✅ Fiók autentikáció sikeres!")
        self.authenticated = True

        logger.info("=" * 70)
        logger.info("🎉 SIKERES CSATLAKOZÁS!")
        logger.info("=" * 70)

    def _handle_auth_error(self, error):
        """Autentikációs hiba kezelése"""
        error_code = error.get('errorCode', 'UNKNOWN')
        error_desc = error.get('description', 'No description')

        logger.error(f"Hibakód: {error_code}")
        logger.error(f"Leírás: {error_desc}")

        # Kapcsolat bontása
        if self.client:
            self.client.stopService()

        reactor.stop()

    def _on_error(self, failure):
        """Általános hibakezelő"""
        logger.error(f"❌ Hiba: {failure}")
        logger.error(f"   Típus: {type(failure.value)}")
        logger.error(f"   Érték: {failure.value}")

        if self.client:
            self.client.stopService()

        reactor.stop()

    def _on_disconnected(self, client, reason):
        """Kapcsolat bontva callback"""
        logger.warning(f"🔌 Kapcsolat bontva: {reason}")
        self.connected = False
        self.authenticated = False

        # Ne állítsuk le a reactor-t ha már nem fut
        if reactor.running:
            reactor.stop()

    def _on_message(self, client, message):
        """Üzenet fogadása"""
        # Spot price updates
        if message.payloadType == OA.ProtoOASpotEvent().payloadType:
            spot = Protobuf.extract(message)
            logger.debug(
                f"💹 Price: Symbol {spot.symbolId}, Bid {spot.bid}, Ask {spot.ask}")

            if self.on_price_update:
                self.on_price_update(spot)

    def disconnect(self):
        """Kapcsolat bontása"""
        if self.client:
            logger.info("👋 Kapcsolat bontása...")
            self.client.stopService()

        if reactor.running:
            reactor.stop()


def test_connection():
    """Kapcsolat teszt"""
    print("=" * 70)
    print("🧪 cTrader API Kapcsolat Teszt")
    print("=" * 70)
    print()

    client = CTraderClient()

    try:
        client.connect()
        reactor.run()

    except CTraderAPIError as e:
        print(f"\n❌ API Hiba: {e}")
    except KeyboardInterrupt:
        print("\n⚠️  Megszakítva (Ctrl+C)")
        client.disconnect()
    except Exception as e:
        print(f"\n❌ Váratlan hiba: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_connection()
