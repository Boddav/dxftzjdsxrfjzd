#!/usr/bin/env python3
"""
Grok API gyors teszt
"""

import os
from openai import OpenAI

# API kulcs
api_key = os.getenv('XAI_API_KEY')

if not api_key:
    print("❌ XAI_API_KEY nincs beállítva!")
    exit(1)

print("=" * 60)
print("🤖 Grok API Teszt")
print("=" * 60)
print(f"🔑 API Key: {api_key[:20]}...")
print()

# Grok client létrehozása
client = OpenAI(
    api_key=api_key,
    base_url="https://api.x.ai/v1"
)

print("📡 Kapcsolódás Grok API-hoz...")

try:
    # Egyszerű teszt kérdés
    response = client.chat.completions.create(
        model="grok-beta",
        messages=[
            {"role": "user", "content": "Say 'Grok API is working!' in one sentence."}
        ],
        max_tokens=50
    )

    answer = response.choices[0].message.content

    print("✅ Grok válasz kapva!")
    print("=" * 60)
    print(f"🤖 Grok: {answer}")
    print("=" * 60)
    print()
    print("🎉 Grok API működik!")
    print("✅ Most már indíthatod a trading botot:")
    print("   export XAI_API_KEY='xai-...'")
    print("   python ai_trading_advisor.py")

except Exception as e:
    print(f"❌ Hiba: {e}")
    print()
    print("💡 Lehetséges okok:")
    print("   1. Helytelen API kulcs")
    print("   2. Internet kapcsolat probléma")
    print("   3. xAI API karbantartás alatt")
