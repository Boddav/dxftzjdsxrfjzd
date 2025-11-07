#!/usr/bin/env python3
"""
cTrader API Kapcsolat Teszt
Ellenőrzi, hogy működik-e a kapcsolat a cTrader API-val
"""

import asyncio
import json
import logging
import sys

try:
    from ctrader_open_api import Client, Protobuf, TcpProtocol, Auth, EndPoints
    from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *
    from ctrader_open_api.messages.OpenApiMessages_pb2 import *
    from twisted.internet import asyncioreactor
except ImportError as e:
    print(f"❌ Import hiba: {e}")
    print("💡 Futtasd: pip install ctrader-open-api")
    sys.exit(1)

# Logging beállítása
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# cTrader API konfiguráció
HOST = "demo.ctraderapi.com"
PORT = 5035


class ConnectionTest:
    """cTrader API kapcsolat tesztelő"""

    def __init__(self):
        self.client = None
        self.credentials = self._load_credentials()

    def _load_credentials(self):
        """Credentials betöltése"""
        try:
            with open('credentials.json', 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error("❌ credentials.json nem található!")
            logger.info("💡 Futtasd: python ctrader_oauth_setup.py")
            raise

    async def connect(self):
        """Kapcsolódás a cTrader API-hoz"""
        try:
            logger.info("=" * 60)
            logger.info("🔌 cTrader API Kapcsolat Teszt")
            logger.info("=" * 60)

            # Reactor inicializálása
            asyncioreactor.install()
            from twisted.internet import reactor

            # Client létrehozása
            self.client = Client(HOST, PORT, reactor)

            logger.info(f"📡 Csatlakozás: {HOST}:{PORT}")

            # Kapcsolódás
            await self.client.connect()
            logger.info("✅ TCP kapcsolat létrejött")

            # Alkalmazás auth
            app_auth_req = ProtoOAApplicationAuthReq()
            app_auth_req.clientId = self.credentials['client_id']
            app_auth_req.clientSecret = self.credentials['client_secret']

            logger.info("🔐 Alkalmazás autentikáció...")
            await self.client.send(app_auth_req)

            # Válasz várása
            app_auth_res = await self.client.receive()

            if app_auth_res.payloadType == ProtoOAApplicationAuthRes().payloadType:
                logger.info("✅ Alkalmazás autentikáció sikeres")
            else:
                logger.error(f"❌ Váratlan válasz: {app_auth_res}")
                return False

            # Account auth
            logger.info("👤 Felhasználói autentikáció...")
            account_auth_req = ProtoOAAccountAuthReq()
            account_auth_req.accessToken = self.credentials['access_token']

            await self.client.send(account_auth_req)
            account_auth_res = await self.client.receive()

            if account_auth_res.payloadType == ProtoOAAccountAuthRes().payloadType:
                logger.info("✅ Felhasználói autentikáció sikeres")
            else:
                logger.error(f"❌ Autentikáció sikertelen: {account_auth_res}")
                return False

            # Fiókok lekérése
            logger.info("📋 Elérhető fiókok lekérése...")
            trader_req = ProtoOATraderReq()
            trader_req.accessToken = self.credentials['access_token']

            await self.client.send(trader_req)
            trader_res = await self.client.receive()

            if trader_res.payloadType == ProtoOATraderRes().payloadType:
                logger.info("✅ Fiókok lekérve")
                logger.info("=" * 60)
                logger.info("📊 Elérhető Trading Fiókok:")
                logger.info("=" * 60)

                for account in trader_res.trader.account:
                    account_type = "DEMO" if account.isLive == False else "LIVE"
                    logger.info(f"  🏦 Account ID: {account.accountId}")
                    logger.info(f"     Típus: {account_type}")
                    logger.info(f"     Egyenleg: ${account.balance / 100:.2f}")
                    logger.info(
                        f"     Tőkeáttét: 1:{account.leverageInCents / 100:.0f}")
                    logger.info(f"     Broker: {account.brokerName}")
                    logger.info("-" * 60)

                # Első account mentése
                if len(trader_res.trader.account) > 0:
                    first_account = trader_res.trader.account[0]
                    self.credentials['account_id'] = first_account.accountId

                    with open('credentials.json', 'w') as f:
                        json.dump(self.credentials, f, indent=2)

                    logger.info(
                        f"💾 Account ID ({first_account.accountId}) mentve a credentials.json-ba")

                logger.info("=" * 60)
                logger.info("🎉 SIKERES KAPCSOLAT!")
                logger.info("=" * 60)
                logger.info("✅ Minden rendben, a bot használatra kész!")
                logger.info("🚀 Indítsd: python ai_trading_advisor.py")
                logger.info("=" * 60)

                return True
            else:
                logger.error(f"❌ Fiókok lekérése sikertelen: {trader_res}")
                return False

        except Exception as e:
            logger.error(f"❌ Hiba történt: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            if self.client:
                self.client.disconnect()
                logger.info("🔌 Kapcsolat bontva")


async def main():
    """Fő függvény"""
    test = ConnectionTest()
    success = await test.connect()

    if not success:
        logger.error("=" * 60)
        logger.error("❌ KAPCSOLAT TESZT SIKERTELEN")
        logger.error("=" * 60)
        logger.info("💡 Ellenőrizd:")
        logger.info("   1. credentials.json létezik")
        logger.info("   2. access_token érvényes")
        logger.info("   3. Internet kapcsolat működik")
        logger.info("   4. cTrader demo account aktív")
        logger.error("=" * 60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n⚠️  Teszt megszakítva (Ctrl+C)")
    except Exception as e:
        logger.error(f"❌ Kritikus hiba: {e}")
