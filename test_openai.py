#!/usr/bin/env python3
"""
OpenAI API gyors teszt
"""

import os
from openai import OpenAI

# API kulcs
api_key = os.getenv('OPENAI_API_KEY')

if not api_key:
    print("❌ OPENAI_API_KEY nincs beállítva!")
    exit(1)

print("=" * 60)
print("🤖 OpenAI API Teszt (GPT-3.5-Turbo)")
print("=" * 60)
print(f"🔑 API Key: {api_key[:20]}...")
print()

# OpenAI client létrehozása
client = OpenAI(api_key=api_key)

print("📡 Kapcsolódás OpenAI API-hoz...")

try:
    # Egyszerű teszt kérdés - GPT-3.5 Turbo
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "user", "content": "Say 'OpenAI GPT-3.5 is working!' in one sentence."}
        ],
        max_tokens=50
    )

    answer = response.choices[0].message.content

    print("✅ GPT-3.5-Turbo válasz kapva!")
    print("=" * 60)
    print(f"🤖 GPT-3.5: {answer}")
    print("=" * 60)
    print()
    print("🎉 OpenAI API működik!")
    print("✅ Most már indíthatod a trading botot:")
    print("   export OPENAI_API_KEY='sk-proj-...'")
    print("   python ai_trading_advisor.py")

except Exception as e:
    print(f"❌ Hiba: {e}")
    print()
    print("💡 Lehetséges okok:")
    print("   1. Helytelen API kulcs")
    print("   2. Nincs kredit az OpenAI fiókon")
    print("   3. Internet kapcsolat probléma")
