#!/usr/bin/env python3
"""
cTrader API Connection Tester
Teszteli, hogy működik-e a cTrader API kapcsolat
"""

import os
import sys
import asyncio
import logging
from dotenv import load_dotenv

# Import saját modulok
from mcp_server import CTraderMCPServer

# Logging konfiguráció
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_connection():
    """
    Tesztelés:
    1. Credentials betöltése
    2. WebSocket kapcsolat
    3. Authentikáció
    4. Account info lekérése
    """

    print("=" * 60)
    print("🤖 cTrader API Connection Test")
    print("=" * 60)
    print()

    # 1. Environment változók ellenőrzése
    load_dotenv()

    print("📋 Credentials ellenőrzése...")
    client_id = os.getenv('CTRADER_CLIENT_ID')
    client_secret = os.getenv('CTRADER_CLIENT_SECRET')
    access_token = os.getenv('CTRADER_ACCESS_TOKEN')
    account_id = os.getenv('CTRADER_ACCOUNT_ID')

    if not client_id:
        print("❌ CTRADER_CLIENT_ID hiányzik!")
        return False
    else:
        print(f"✅ Client ID: {client_id[:20]}...")

    if not client_secret:
        print("❌ CTRADER_CLIENT_SECRET hiányzik!")
        return False
    else:
        print(f"✅ Client Secret: {'*' * 20}")

    if not access_token:
        print("⚠️  Access token hiányzik - OAuth szükséges!")
        print("   Futtasd: python ctrader_oauth_setup.py")
        return False
    else:
        print(f"✅ Access Token: {access_token[:20]}...")

    if account_id:
        print(f"✅ Account ID: {account_id}")
    else:
        print("⚠️  Account ID nincs megadva")

    print()

    # 2. MCP Server kapcsolat teszt
    print("🔌 Kapcsolódás cTrader API-hoz...")

    try:
        # MCP Server inicializálás
        mcp_server = CTraderMCPServer()

        print("📡 Credentials betöltése...")
        credentials = mcp_server.load_credentials()

        print("🌐 WebSocket kapcsolat...")
        await mcp_server.connect()

        if mcp_server.connected:
            print("✅ WebSocket kapcsolat sikeres!")
        else:
            print("❌ WebSocket kapcsolat sikertelen!")
            return False

        print()

        # 3. Account info lekérése
        print("📊 Account információk lekérése...")

        try:
            account_info = await mcp_server.get_account_info()

            print("✅ Account info sikeresen lekérve!")
            print(f"   Balance: ${account_info.get('balance', 'N/A')}")
            print(f"   Equity: ${account_info.get('equity', 'N/A')}")
            print(f"   Currency: {account_info.get('currency', 'N/A')}")
            print()

        except Exception as e:
            print(f"❌ Account info hiba: {str(e)}")
            return False

        # 4. Market data teszt
        print("📈 Market data teszt (XAUUSD)...")

        try:
            market_data = await mcp_server.get_market_data("XAUUSD")

            print("✅ Market data sikeresen lekérve!")
            print(f"   Symbol: {market_data.get('symbol', 'N/A')}")
            print(f"   Bid: {market_data.get('bid', 'N/A')}")
            print(f"   Ask: {market_data.get('ask', 'N/A')}")
            print(f"   Spread: {market_data.get('spread', 'N/A')}")
            print()

        except Exception as e:
            print(f"⚠️  Market data hiba (nem kritikus): {str(e)}")

        # 5. Disconnect
        print("🔌 Kapcsolat bontása...")
        await mcp_server.disconnect()
        print("✅ Kapcsolat bezárva")
        print()

        # Összefoglaló
        print("=" * 60)
        print("✅ cTrader API kapcsolat SIKERES!")
        print("=" * 60)
        print()
        print("🎉 A bot készen áll a használatra!")
        print()

        return True

    except Exception as e:
        print()
        print("=" * 60)
        print(f"❌ Hiba történt: {str(e)}")
        print("=" * 60)
        print()

        logger.error(f"Connection test error: {str(e)}", exc_info=True)
        return False


if __name__ == '__main__':
    # Futtatás
    result = asyncio.run(test_connection())

    if result:
        print("✅ Teszt sikeres - A bot használatra kész!")
        sys.exit(0)
    else:
        print("❌ Teszt sikertelen - Ellenőrizd a credentials-eket és próbáld újra az OAuth-ot")
        print()
        print("Következő lépés:")
        print("  python ctrader_oauth_setup.py")
        sys.exit(1)
