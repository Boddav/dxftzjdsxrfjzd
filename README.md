# 🤖 AI Trading Advisor

**Claude AI alapú automatizált trading bot cTrader API-val**

GitHub Codespaces kompatibilis, teljes körű AI trading megoldás arany (XAUUSD) és forex kereskedéshez.

---

## 🌟 Funkciók

- ✅ **Claude AI döntéshozatal** - Anthropic Claude Sonnet 4.5 alapú elemzés
- ✅ **cTrader API integráció** - Valós idejű piaci adatok és order végrehajtás
- ✅ **Model Context Protocol (MCP)** - Strukturált AI eszköz használat
- ✅ **Technikai indikátorok** - SMA, EMA, RSI, Bollinger Bands
- ✅ **Kockázatkezelés** - Maximum 2% kockázat per trade
- ✅ **Automatikus OAuth** - Egyszerű cTrader fiók csatlakoztatás
- ✅ **GitHub Codespaces ready** - DevContainer előkonfigurálva
- ✅ **Magyar dokumentáció** - Teljes magyar nyelvű útmutató

---

## 📋 Előkövetelmények

1. **GitHub account** - Codespaces használatához
2. **cTrader account** - Demo vagy Live (javasolt: demo)
3. **Anthropic API kulcs** - [Szerezz be itt](https://console.anthropic.com/)

---

## 🚀 Gyors Telepítés

### 1️⃣ GitHub Codespaces Indítás

```bash
# 1. Fork vagy clone-ozd ezt a repository-t
# 2. Nyisd meg GitHub Codespaces-ben:
#    Code -> Codespaces -> Create codespace on main
```

### 2️⃣ Függőségek Telepítése

```bash
pip install -r requirements.txt
```

### 3️⃣ OAuth Setup (cTrader Csatlakozás)

```bash
python ctrader_oauth_setup.py
```

**Mit fog ez csinálni?**
- HTTP szerver indul a port 8080-on
- Codespaces automatikusan ad egy publikus URL-t
- Böngészőben megnyílik a cTrader OAuth oldal
- Engedélyezd a hozzáférést
- Automatikusan létrejön a `credentials.json` fájl

### 4️⃣ Anthropic API Kulcs Beállítása

```bash
export ANTHROPIC_API_KEY='your-api-key-here'
```

**Vagy hozz létre `.env` fájlt:**

```bash
cp .env.example .env
# Szerkeszd a .env fájlt és add meg az API kulcsod
```

### 5️⃣ Trading Bot Indítása

```bash
python ai_trading_advisor.py
```

---

## 📂 Projekt Struktúra

```
ai-trading-advisor/
├── .devcontainer/
│   └── devcontainer.json          # GitHub Codespaces konfig
├── ctrader_oauth_setup.py         # OAuth szerver (cTrader auth)
├── mcp_server.py                  # Model Context Protocol server
├── ai_trading_advisor.py          # Fő trading bot
├── requirements.txt               # Python függőségek
├── .env.example                   # Példa environment változók
├── .gitignore                     # Git ignore fájlok
└── README.md                      # Ez a dokumentáció
```

---

## 🔧 Komponensek Részletesen

### 1. **ctrader_oauth_setup.py** - OAuth Szerver

**Funkciók:**
- Automatikus Codespaces URL észlelés
- Gyönyörű HTML UI az OAuth flow-hoz
- Automatikus `credentials.json` generálás
- Account ID automatikus lekérése

**Használat:**

```bash
python ctrader_oauth_setup.py
```

**Kimenet:**
```
🤖 AI Trading Advisor - cTrader OAuth Setup
============================================================
📍 Redirect URI: https://your-codespace-8080.preview.app.github.dev/callback
🌐 Server Port: 8080

🚀 OAuth szerver elindult!
👉 Nyisd meg böngészőben: https://your-codespace-8080.preview.app.github.dev
```

---

### 2. **mcp_server.py** - MCP Server

**Model Context Protocol eszközök Claude AI számára:**

| Eszköz | Leírás | Paraméterek |
|--------|--------|-------------|
| `get_market_data` | Aktuális piaci árak (bid, ask, spread) | `symbol` (pl. XAUUSD) |
| `get_positions` | Nyitott pozíciók listája | - |
| `place_order` | Piaci megbízás leadása | `symbol`, `side`, `volume`, `stop_loss`, `take_profit` |
| `get_candles` | Történeti gyertyák (OHLC) | `symbol`, `timeframe`, `count` |
| `get_account_info` | Számla információk | - |

**API Használat:**

```python
from mcp_server import CTraderMCPServer

server = CTraderMCPServer()
await server.connect()

# Piaci adatok
market_data = await server.get_market_data("XAUUSD")
print(f"Bid: {market_data['bid']}, Ask: {market_data['ask']}")

# Megbízás
order = await server.place_order(
    symbol="XAUUSD",
    side="BUY",
    volume=10000,  # 0.01 lot
    stop_loss=2600.0,
    take_profit=2700.0
)
```

---

### 3. **ai_trading_advisor.py** - AI Trading Bot

**Architektúra:**

```
┌─────────────────────────────────────────────────────────┐
│                   AI Trading Advisor                    │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────────┐    ┌─────────────────────────┐   │
│  │  Market Data     │───▶│  Technical Analysis     │   │
│  │  (cTrader API)   │    │  - SMA, EMA, RSI        │   │
│  └──────────────────┘    │  - Bollinger Bands      │   │
│                          └───────────┬─────────────┘   │
│                                      │                   │
│                          ┌───────────▼─────────────┐   │
│                          │   Claude AI Decision    │   │
│                          │   (Anthropic API)       │   │
│                          └───────────┬─────────────┘   │
│                                      │                   │
│  ┌──────────────────┐    ┌───────────▼─────────────┐   │
│  │  Risk Manager    │───▶│   Order Execution       │   │
│  │  - Max 2% risk   │    │   (MCP Server)          │   │
│  │  - Max 3 trades  │    └─────────────────────────┘   │
│  └──────────────────┘                                   │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

**Technikai Indikátorok:**

```python
class TechnicalIndicators:
    @staticmethod
    def sma(data, period):
        """Simple Moving Average"""

    @staticmethod
    def ema(data, period):
        """Exponential Moving Average"""

    @staticmethod
    def rsi(data, period=14):
        """Relative Strength Index"""

    @staticmethod
    def bollinger_bands(data, period=20, std_dev=2):
        """Bollinger Bands"""
```

**Kockázatkezelés:**

```python
class RiskManager:
    def __init__(self, max_risk_per_trade=0.02, max_open_positions=3):
        """
        max_risk_per_trade: Maximum 2% kockázat per trade
        max_open_positions: Maximum 3 nyitott pozíció
        """
```

**Trading Loop (60 másodpercenként):**

1. **Piaci adatok lekérése** - XAUUSD bid/ask, történeti gyertyák
2. **Technikai analízis** - Indikátorok számítása
3. **Claude AI konzultáció** - Döntés kérése az AI-tól
4. **Trade végrehajtás** - Order leadása (ha szükséges)

---

## 🧠 Claude AI Prompt Példa

A bot a következő formátumban konzultál Claude AI-val:

```
You are an expert trading advisor analyzing XAUUSD (Gold).

**Current Market Data:**
- Bid: 2650.50
- Ask: 2650.80
- Spread: 0.30

**Technical Analysis:**
- Current Price: 2650.65
- SMA 20: 2645.20
- SMA 50: 2640.10
- RSI: 45.30
- Trend: BULLISH

**Trading Rules:**
- Maximum Risk per Trade: 2%
- RSI Overbought: > 70 (consider SELL)
- RSI Oversold: < 30 (consider BUY)

Based on this analysis, provide your trading decision in JSON format:
{
    "action": "BUY" or "SELL" or "HOLD",
    "confidence": 0.0 to 1.0,
    "reasoning": "your detailed reasoning",
    "stop_loss_pips": 20,
    "take_profit_pips": 40
}
```

---

## ⚙️ Konfiguráció

### Trading Paraméterek

Szerkeszd az `ai_trading_advisor.py` fájlban:

```python
# Kockázatkezelés
risk_manager = RiskManager(
    max_risk_per_trade=0.02,  # 2% kockázat
    max_open_positions=3       # Max 3 trade egyszerre
)

# Trading szimbólum
symbol = "XAUUSD"  # Arany (változtatható: EURUSD, GBPUSD, stb.)

# Loop gyakoriság
await asyncio.sleep(60)  # 60 másodperc (1 perc)
```

### Technikai Indikátor Paraméterek

```python
# Mozgóátlagok
sma_20 = indicators.sma(close_prices, 20)  # 20 periódusos SMA
sma_50 = indicators.sma(close_prices, 50)  # 50 periódusos SMA

# RSI
rsi = indicators.rsi(close_prices, 14)  # 14 periódusos RSI

# Bollinger Bands
bb = indicators.bollinger_bands(close_prices, 20, 2)  # 20 periódus, 2 szórás
```

---

## 📊 Használati Példák

### Egyszerű Indítás (Demo Account)

```bash
# 1. OAuth setup
python ctrader_oauth_setup.py

# 2. API kulcs export
export ANTHROPIC_API_KEY='your-key'

# 3. Bot indítása
python ai_trading_advisor.py
```

### Monitoring és Naplózás

```bash
# Részletes logolás
export LOG_LEVEL=DEBUG
python ai_trading_advisor.py

# Log file-ba mentés
python ai_trading_advisor.py 2>&1 | tee trading.log
```

### Manuális Teszt (MCP Server)

```bash
# MCP eszközök tesztelése
python mcp_server.py
```

---

## 🛡️ Biztonsági Megjegyzések

### ⚠️ FONTOS

- **SOHA ne commitolj credentials.json-t** - Git ignore-ban van
- **API kulcsokat `.env` fájlban tárold** - Ne hardcode-old
- **Először demo accounton tesztelj** - Nem valós pénz
- **Limits beállítása** - Max risk és max trades
- **Regular monitoring** - Ne hagyd felügyelet nélkül

### Best Practices

1. **Demo Account First** - Minimum 1 hét teszt demo accounton
2. **Small Positions** - Kezdd kis lot méretekkel (0.01)
3. **Stop Loss Always** - Mindig használj stop loss-t
4. **Daily Review** - Napi szinten nézd át a trade-eket
5. **Backtesting** - Tesztelj történeti adatokon

---

## 🐛 Hibaelhárítás

### `credentials.json` nem található

```bash
# Futtasd újra az OAuth setup-ot
python ctrader_oauth_setup.py
```

### `ANTHROPIC_API_KEY` hiányzik

```bash
# Export environment variable
export ANTHROPIC_API_KEY='your-api-key'

# VAGY hozz létre .env fájlt
echo "ANTHROPIC_API_KEY=your-api-key" > .env
```

### cTrader API kapcsolódási hiba

1. Ellenőrizd az internet kapcsolatot
2. Győződj meg róla, hogy a demo account aktív
3. Próbáld újra az OAuth flow-t
4. Nézd meg a `credentials.json` tartalmát

### "Port already in use" hiba

```bash
# Állítsd le a futó szervert
lsof -ti:8080 | xargs kill -9

# Vagy használj másik portot
# Szerkeszd: PORT = 8081 a ctrader_oauth_setup.py-ban
```

---

## 📈 Példa Kimenet

```
============================================================
🤖 AI Trading Advisor - Claude AI + cTrader
============================================================

✅ Minden rendben, bot indítása...
============================================================
🚀 Trading bot indítása...
🤖 AI Trading Advisor inicializálva
✅ Csatlakozva a cTrader API-hoz
💰 Számla: $10000.00

📊 Analízis: Trend=BULLISH, RSI=45.30, Price=2650.65
🤖 AI Döntés: BUY (confidence: 0.85)
💭 Indoklás: Strong bullish trend with RSI in neutral zone. SMA crossover suggests upward momentum.

✅ Trade végrehajtva: BUY 0.01 lot @ 2650.80
   SL: 2648.80, TP: 2654.80

✅ Trading loop befejezve - Döntés: BUY
```

---

## 🔗 Hasznos Linkek

- [cTrader Open API Docs](https://help.ctrader.com/open-api/)
- [Anthropic Claude API](https://docs.anthropic.com/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [GitHub Codespaces](https://github.com/features/codespaces)

---

## 📝 License

MIT License - Szabad felhasználás saját felelősségre.

---

## ⚖️ Jogi Nyilatkozat

**FIGYELEM:** Ez egy oktatási célú projekt. Trading valós pénzzel jelentős kockázatokat hordoz.

- ❌ Nem pénzügyi tanácsadás
- ❌ Nincs garancia a nyereségre
- ❌ Használat saját felelősségre
- ✅ Mindig demo accounton kezdj
- ✅ Soha ne kereskedj pénzzel, amit nem engedhetsz meg elveszíteni

---

## 🙋 Támogatás

Ha kérdésed van:

1. Nézd meg a **Hibaelhárítás** szekciót
2. Ellenőrizd a logokat
3. Olvasd el a [cTrader API dokumentációt](https://help.ctrader.com/open-api/)
4. Nyiss egy GitHub Issue-t

---

## 🎉 Köszönetnyilvánítás

- **Anthropic** - Claude AI
- **Spotware** - cTrader API
- **GitHub** - Codespaces

---

**Készítette Claude Code 🤖**

*Happy Trading! 📈*
