# 🚀 Teljes Setup Útmutató - GitHub → cTrader

**AI Trading Advisor teljes telepítése és konfigurálása lépésről lépésre**

---

## 📋 Szükséges Fiókok és Kulcsok

### 1. GitHub Account
- Regisztráció: https://github.com/signup
- Szükséges a repository használatához és Codespaces-hez

### 2. cTrader Account (Demo ajánlott kezdéshez)
- Regisztráció: https://ctrader.com/
- **Demo account** - Kezdéshez ideális, nincs valós pénz kockázat
- **Live account** - Csak tapasztalat után!

### 3. Anthropic API Kulcs (Claude AI)
- Regisztráció: https://console.anthropic.com/
- API kulcs generálás: Settings → API Keys
- Díjazás: Pay-as-you-go (kb. $0.003 per döntés)

---

## 🔧 Telepítés GitHub-ról

### Opció A: GitHub Codespaces (Ajánlott - Felhő alapú)

```bash
# 1. Fork vagy clone-ozd a repository-t
# GitHub webes felületen: Fork gomb

# 2. Codespaces indítása
# Code gomb → Codespaces → Create codespace on main

# 3. Automatikus setup (~2 perc)
# A .devcontainer/devcontainer.json automatikusan telepít mindent
```

### Opció B: Helyi Telepítés

```bash
# 1. Repository klónozása
git clone https://github.com/yourusername/ai-trading-advisor.git
cd ai-trading-advisor

# 2. Python virtual environment létrehozása
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# VAGY
venv\Scripts\activate  # Windows

# 3. Függőségek telepítése
pip install -r requirements.txt
```

---

## 🔐 cTrader API Setup (OAuth)

### 1. cTrader Application Létrehozása

1. Jelentkezz be: https://ctrader.com/
2. Menj a: **cTrader Open API** → **Applications**
3. Kattints: **Create New Application**

**Beállítások:**
```
Application Name: AI Trading Advisor
Redirect URI: http://localhost:8080/callback
             (vagy Codespaces esetén: https://your-codespace-8080.preview.app.github.dev/callback)
Permissions: Trading, Account Read
```

4. **Mentsd el:**
   - `Client ID` (pl.: 13617_NoiIy9DOCJXwKnJEE0...)
   - `Client Secret` (pl.: M6qpm5h25hDHsq31...)

### 2. OAuth Folyamat Futtatása

```bash
# OAuth szerver indítása
python ctrader_oauth_setup.py
```

**Mit vársz:**
```
🤖 AI Trading Advisor - cTrader OAuth Setup
============================================================
📍 Redirect URI: http://localhost:8080/callback
🌐 Server Port: 8080

🚀 OAuth szerver elindult!
👉 Nyisd meg böngészőben: http://localhost:8080
```

### 3. Böngészőben Engedélyezés

1. Automatikusan megnyílik a böngésző (vagy kattints a linkre)
2. **cTrader login** - Jelentkezz be
3. **Engedélyezés** - "Allow" gomb
4. **Redirect vissza** - Automatikus átirányítás
5. **Siker!** - `credentials.json` létrejött

**credentials.json tartalma:**
```json
{
    "client_id": "13617_NoiIy...",
    "client_secret": "M6qpm5h...",
    "access_token": "eyJhbGc...",
    "refresh_token": "def502...",
    "account_id": "1234567",
    "expires_at": 1234567890
}
```

---

## 🤖 Claude AI API Setup

### 1. API Kulcs Beszerzése

1. Nyisd meg: https://console.anthropic.com/
2. **Settings** → **API Keys**
3. **Create Key** - Adj meg egy nevet (pl.: "Trading Bot")
4. **Másold ki** a kulcsot (pl.: `sk-ant-api03-...`)

### 2. API Kulcs Beállítása

**Opció A: Environment Variable (Ideiglenes)**
```bash
export ANTHROPIC_API_KEY='sk-ant-api03-your-key-here'
```

**Opció B: .env Fájl (Ajánlott - Tartós)**
```bash
# .env fájl létrehozása
cp .env.example .env

# Szerkesztés
nano .env
# VAGY
vim .env
```

**.env tartalom:**
```bash
# Anthropic API
ANTHROPIC_API_KEY=sk-ant-api03-your-actual-key-here

# Admin Interface
ADMIN_PORT=5000
SECRET_KEY=generate-random-secret-key-here
FLASK_DEBUG=False

# Trading Parameters
MAX_RISK_PER_TRADE=0.02
MAX_OPEN_POSITIONS=3
LOG_LEVEL=INFO
```

---

## 🎯 Admin Felület Indítása

### 1. Admin Szerver Indítása

```bash
python admin_interface.py
```

**Kimenet:**
```
╔════════════════════════════════════════════╗
║   AI Trading Advisor - Admin Interface    ║
╚════════════════════════════════════════════╝

🌐 Admin felület: http://localhost:5000
🔧 Debug mód: False

Nyomd meg Ctrl+C a leállításhoz
 * Running on http://0.0.0.0:5000
```

### 2. Böngészőben Megnyitás

**Helyi:** http://localhost:5000
**Codespaces:** A portforwarding automatikus, kattints a linkre

### 3. Dashboard Használat

#### 📊 Dashboard Oldal
- **Bot státusz** - Fut/Leáll jelzés
- **Indítás gomb** - ▶ Bot elindítása
- **Leállítás gomb** - ⏹ Bot leállítása
- **Mai kereskedések** - Hány trade történt ma
- **Mai P&L** - Profit/Loss összesítő
- **Aktív pozíciók** - Táblázat nyitott trade-ekkel
- **Előzmények** - Utolsó 10 kereskedés

#### ⚙️ Beállítások Oldal
- **cTrader API** - Client ID, Secret, Account ID
- **Claude AI** - Anthropic API kulcs
- **Trading paraméterek** - Max pozíciók, kockázat
- **Mentés** - Konfiguráció mentése

#### 📝 Naplók Oldal
- **Valós idejű naplók** - System logs stream
- **Szűrés** - INFO/WARNING/ERROR
- **Automatikus frissítés** - 10 másodpercenként

---

## 🎮 Bot Indítása és Használat

### Opció 1: Admin Felületen Keresztül (Ajánlott)

1. **Nyisd meg:** http://localhost:5000
2. **Ellenőrzés:** Nézd meg a Beállítások oldalt, hogy minden kulcs be van-e állítva
3. **Indítás:** Dashboard → ▶ Indítás gomb
4. **Monitoring:** Kövesd a Dashboard-on a státuszt és pozíciókat

### Opció 2: Közvetlenül Parancssorból

```bash
# Egyszerű indítás
python ai_trading_advisor.py

# Részletes logolással
export LOG_LEVEL=DEBUG
python ai_trading_advisor.py

# Log fájlba mentés
python ai_trading_advisor.py 2>&1 | tee trading.log
```

---

## 📊 Működés Áttekintése

### Trading Loop (60 másodpercenként)

```
1. Piaci adatok lekérése
   ↓
2. Technikai analízis (SMA, RSI, Bollinger)
   ↓
3. Claude AI döntés kérése
   ↓
4. Kockázat ellenőrzése
   ↓
5. Trade végrehajtás (ha szükséges)
   ↓
6. 60 mp várakozás → újra 1.
```

### Döntési Logika

**Claude AI kapja:**
- Aktuális ár (bid/ask)
- Technikai indikátorok (SMA, RSI, trend)
- Kockázati szabályok
- Előző döntések kontextusa

**Claude AI válasza:**
```json
{
    "action": "BUY",
    "confidence": 0.85,
    "reasoning": "Strong bullish momentum with RSI neutral",
    "stop_loss_pips": 20,
    "take_profit_pips": 40
}
```

**Bot végrehajtja:**
- Ha confidence > 0.7 → Trade
- Ha confidence < 0.7 → HOLD
- Risk manager ellenőrzi
- Order leadása cTrader-en keresztül

---

## 🛡️ Biztonsági Checklist

### ✅ Indítás Előtt

- [ ] **Demo account** használata (nem live!)
- [ ] **credentials.json** git ignore-ban van
- [ ] **API kulcsok** .env fájlban (nem commitolva)
- [ ] **Max risk** beállítva (ajánlott: 1-2%)
- [ ] **Max positions** beállítva (ajánlott: 3)
- [ ] **Stop loss** mindig engedélyezve

### ⚠️ Futás Közben

- [ ] **Regular monitoring** - Legalább naponta egyszer
- [ ] **Log review** - Nézd át a döntéseket
- [ ] **Performance tracking** - P&L nyomon követése
- [ ] **Account balance** - Ne kereskedj túl sokat

### 🚨 Vészhelyzet

**Azonnal állítsd le a bot-ot, ha:**
- Szokatlan veszteségek (-5% egy nap alatt)
- API hibák sorozata
- Nem várt viselkedés
- Hálózati problémák

**Leállítás:**
- Admin felület: ⏹ Leállítás gomb
- Parancssor: `Ctrl+C`
- Vészhelyzet: `killall python3`

---

## 🐛 Gyakori Problémák és Megoldások

### 1. "credentials.json not found"

**Megoldás:**
```bash
python ctrader_oauth_setup.py
# Kövesd az OAuth folyamatot újra
```

### 2. "ANTHROPIC_API_KEY not set"

**Megoldás:**
```bash
# .env fájl létrehozása
cp .env.example .env
# Szerkesztés és kulcs hozzáadása
nano .env
```

### 3. "Port 8080 already in use"

**Megoldás:**
```bash
# Port ellenőrzése
lsof -i :8080
# Folyamat leállítása
kill -9 <PID>
```

### 4. "Cannot connect to cTrader API"

**Ellenőrzések:**
- [ ] Internet kapcsolat rendben van?
- [ ] cTrader account aktív?
- [ ] credentials.json érvényes?
- [ ] Access token nem járt le?

**Token frissítés:**
```bash
# OAuth újrafuttatása
python ctrader_oauth_setup.py
```

### 5. "Admin interface 500 error"

**Megoldás:**
```bash
# Részletes hiba logok
export FLASK_DEBUG=True
python admin_interface.py
# Nézd meg a teljes stack trace-t
```

---

## 📈 Következő Lépések

### 1. Első Nap - Teszt

- ✅ Bot indítása demo accounton
- ✅ 1-2 trade megfigyelése
- ✅ Log review
- ✅ Minden működik?

### 2. Első Hét - Optimalizálás

- 📊 Trading paraméterek finomhangolása
- 📝 Döntések elemzése
- 🔧 Indikátor súlyok állítása
- 📈 Performance tracking

### 3. Hosszú Távú - Skálázás

- 💼 További szimbólumok (EURUSD, GBPUSD)
- 🤖 Multiple bot instances
- 📊 Backtesting implementálás
- 🚀 Advanced stratégiák

---

## 🎓 Hasznos Források

### Dokumentációk

- **cTrader API:** https://help.ctrader.com/open-api/
- **Claude API:** https://docs.anthropic.com/
- **Flask Docs:** https://flask.palletsprojects.com/

### Közösség

- **GitHub Issues:** Kérdések és hibajelentések
- **cTrader Forum:** https://ctrader.com/forum/
- **Trading Közösségek:** Reddit r/algotrading

---

## ✅ Setup Checklist - Összefoglaló

```
[ ] 1. GitHub account létrehozva
[ ] 2. Repository fork/clone
[ ] 3. Codespaces/helyi környezet setup
[ ] 4. Python függőségek telepítve
[ ] 5. cTrader account létrehozva (DEMO!)
[ ] 6. cTrader API application regisztrálva
[ ] 7. OAuth folyamat lefuttatva
[ ] 8. credentials.json létrejött
[ ] 9. Anthropic account létrehozva
[ ] 10. Claude API kulcs generálva
[ ] 11. .env fájl létrehozva és kitöltve
[ ] 12. Admin felület elindul (http://localhost:5000)
[ ] 13. Bot sikeresen elindul
[ ] 14. Első trade végrehajtva (demo!)
[ ] 15. Monitoring működik
```

---

**🎉 Gratulálok! Az AI Trading Advisor elkészült és működik!**

**⚠️ EMLÉKEZTETŐ:** Mindig demo accounton kezdj és soha ne kereskedj pénzzel, amit nem engedhetsz meg elveszíteni!

---

**Készítette: Claude Code 🤖**
*Verzió: 1.0 - 2026-06-12*
