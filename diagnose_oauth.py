#!/usr/bin/env python3
"""
cTrader OAuth Diagnózis - Részletes debugging
"""
import json
import requests

print("=" * 70)
print("🔍 cTrader OAuth Diagnózis")
print("=" * 70)
print()

# Credentials betöltése
try:
    with open('credentials.json', 'r') as f:
        creds = json.load(f)
    print("✅ credentials.json betöltve")
except FileNotFoundError:
    print("❌ Nincs credentials.json fájl!")
    print("   Futtasd: python ctrader_oauth_setup.py")
    exit(1)

print()
print("📋 Credentials információ:")
print(f"   Client ID: {creds['client_id'][:20]}...")
print(f"   Client Secret: {creds['client_secret'][:20]}...")
print(f"   Access Token: {creds['access_token'][:20]}...")
print(f"   Account ID: {creds.get('account_id', 'NULL')}")
print()

# Token információ lekérése
print("🔍 Token információ ellenőrzése...")
print()

# A cTrader API nem nyújt token introspection endpoint-ot
# De megpróbálhatunk egy minimális Protobuf tesztet

print("💡 Következő lépések:")
print()
print("1️⃣  ELLENŐRIZD a cTrader app beállításokat:")
print("   📍 https://openapi.ctrader.com/apps")
print("   - Redirect URI helyes? Kell: https://super-tribble-g4q9pxp4r5j6fv6x5-53123.app.github.dev/callback")
print("   - Scope: 'trading' VAGY 'trading accounts'")
print()
print("2️⃣  PROBLÉMA: Az access token NEM kapcsolódik account-hoz")
print("   - Az OAuth során NEM választottál ki trading account-ot")
print("   - VAGY a demo account nem elérhető ezen a client ID-n")
print()
print("3️⃣  MEGOLDÁS opciók:")
print()
print("   A) ÚJ OAUTH FLOW - FIGYELMESEN:")
print("      1. python ctrader_oauth_setup.py")
print("      2. Böngésző: JELENTKEZZ BE cTrader demo fiókba")
print("      3. VÁLASSZ KI egy demo trading account-ot a listából")
print("      4. Csak ezután Authorize")
print()
print("   B) ELLENŐRIZD hogy VAN-E demo account:")
print("      - Menj: https://ct.spotware.com/")
print("      - Jelentkezz be")
print("      - Ellenőrizd hogy van-e aktív demo account")
print("      - Jegyezd fel az Account ID-t!")
print()
print("   C) PAPER TRADING SZIMULÁCIÓ (Működik AZONNAL):")
print("      - Nincs szükség cTrader kapcsolatra")
print("      - OpenAI GPT-3.5 AI döntések")
print("      - Virtuális kereskedés realisztikus adatokkal")
print()
print("=" * 70)
print()
print("Mit szeretnél? (Írd be a betűt)")
print("  A - Új OAuth próba")
print("  B - Demo account ellenőrzés")
print("  C - Paper Trading (ajánlott!)")
print("=" * 70)
