#!/usr/bin/env python3
"""
Egyszerű cTrader API Kapcsolat Teszt
"""

import json
import requests
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# API Endpoints
TOKEN_URL = "https://openapi.ctrader.com/apps/token"
ACCOUNTS_URL = "https://openapi.ctrader.com/apps/accounts"


def load_credentials():
    """Credentials betöltése"""
    try:
        with open('credentials.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("❌ credentials.json nem található!")
        return None


def test_token_refresh(creds):
    """Access token frissítése"""
    logger.info("🔄 Access token frissítése...")

    data = {
        'grant_type': 'refresh_token',
        'refresh_token': creds['refresh_token'],
        'client_id': creds['client_id'],
        'client_secret': creds['client_secret']
    }

    try:
        response = requests.post(TOKEN_URL, data=data)

        if response.status_code == 200:
            token_data = response.json()
            logger.info("✅ Token frissítés sikeres")

            # Token mentése
            creds['access_token'] = token_data['access_token']
            creds['refresh_token'] = token_data['refresh_token']

            with open('credentials.json', 'w') as f:
                json.dump(creds, f, indent=2)

            logger.info("💾 Új token mentve")
            return True
        else:
            logger.error(
                f"❌ Token frissítés sikertelen: {response.status_code}")
            logger.error(f"   Válasz: {response.text}")
            return False

    except Exception as e:
        logger.error(f"❌ Hiba: {e}")
        return False


def test_accounts(creds):
    """Elérhető fiókok lekérése"""
    logger.info("📋 Trading fiókok lekérése...")

    headers = {
        'Authorization': f"Bearer {creds['access_token']}"
    }

    try:
        response = requests.get(ACCOUNTS_URL, headers=headers)

        if response.status_code == 200:
            accounts_data = response.json()
            logger.info("✅ Fiókok lekérve")
            logger.info("=" * 60)
            logger.info("📊 Elérhető Trading Fiókok:")
            logger.info("=" * 60)

            if 'data' in accounts_data:
                for account in accounts_data['data']:
                    account_type = "LIVE" if account.get(
                        'live', False) else "DEMO"
                    logger.info(f"  🏦 Account ID: {account.get('accountId')}")
                    logger.info(f"     Típus: {account_type}")
                    logger.info(
                        f"     Egyenleg: ${account.get('balance', 0) / 100:.2f}")
                    logger.info(
                        f"     Deviza: {account.get('currency', 'N/A')}")
                    logger.info(
                        f"     Broker: {account.get('brokerName', 'N/A')}")
                    logger.info("-" * 60)

                # Első account mentése
                if len(accounts_data['data']) > 0:
                    first_account = accounts_data['data'][0]
                    creds['account_id'] = first_account['accountId']

                    with open('credentials.json', 'w') as f:
                        json.dump(creds, f, indent=2)

                    logger.info(
                        f"💾 Account ID ({first_account['accountId']}) mentve")

            logger.info("=" * 60)
            logger.info("🎉 SIKERES KAPCSOLAT!")
            logger.info("=" * 60)
            logger.info("✅ A cTrader API elérhető és működik!")
            logger.info("=" * 60)
            return True

        elif response.status_code == 401:
            logger.warning("⚠️  Token lejárt, frissítés szükséges...")
            if test_token_refresh(creds):
                return test_accounts(creds)  # Újrapróbálás új tokennel
            return False
        else:
            logger.error(
                f"❌ Fiókok lekérése sikertelen: {response.status_code}")
            logger.error(f"   Válasz: {response.text}")
            return False

    except Exception as e:
        logger.error(f"❌ Hiba: {e}")
        return False


def main():
    """Fő függvény"""
    logger.info("=" * 60)
    logger.info("🔌 cTrader API REST Kapcsolat Teszt")
    logger.info("=" * 60)

    # Credentials betöltése
    creds = load_credentials()
    if not creds:
        logger.error("❌ Nem sikerült betölteni a credentials.json fájlt")
        logger.info("💡 Futtasd: python ctrader_oauth_setup.py")
        return

    logger.info(f"📁 Credentials betöltve")
    logger.info(f"   Client ID: {creds['client_id'][:20]}...")
    logger.info(f"   Access Token: {creds['access_token'][:20]}...")
    logger.info("=" * 60)

    # Fiókok tesztelése
    success = test_accounts(creds)

    if not success:
        logger.error("=" * 60)
        logger.error("❌ KAPCSOLAT TESZT SIKERTELEN")
        logger.error("=" * 60)
        logger.info("💡 Lehetséges okok:")
        logger.info("   1. Token lejárt - próbáld újra az OAuth setup-ot")
        logger.info("   2. Internet kapcsolat probléma")
        logger.info("   3. cTrader API karbantartás alatt")
        logger.info("   4. Demo account nem aktív")
        logger.error("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n⚠️  Teszt megszakítva (Ctrl+C)")
    except Exception as e:
        logger.error(f"❌ Kritikus hiba: {e}")
        import traceback
        traceback.print_exc()
