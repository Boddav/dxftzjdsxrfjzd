# 🧪 cTrader API Tesztelési Útmutató

## ⚠️ FONTOS BIZTONSÁGI FIGYELMEZTETÉS

**SOHA NE OSZD MEG NYILVÁNOSAN:**
- ❌ Client Secret
- ❌ Access Token
- ❌ API kulcsokat

**Amit megosztható:**
- ✅ Client ID (első 10 karakter)
- ✅ Account ID (opcionális)

---

## 📋 Tesztelési lépések

### **1️⃣ Biztonsági ellenőrzés (KÖTELEZŐ)**

Ha már megosztottad a credentials-eket, AZONNAL változtasd meg:

1. Menj: https://connect.spotware.com/apps
2. Jelentkezz be cTrader fiókkal
3. Keresd meg az alkalmazást (Client ID: `13619_...`)
4. **Regenerate Secret** vagy töröld és hozz létre újat

---

### **2️⃣ Credentials beállítása**

Használd az **Admin UI-t** vagy `.env` fájlt:

#### **A) Admin UI (AJÁNLOTT):**

1. Nyisd meg: http://localhost:5000 (vagy Replit URL)
2. Menj: **Beállítások** fül
3. Töltsd ki:
   ```
   Client ID: [ÚJ client ID]
   Client Secret: [ÚJ secret]
   Account ID: 9007390
   ```
4. **Mentés** gomb

#### **B) .env fájl (Alternatíva):**

```bash
CTRADER_CLIENT_ID=your_new_client_id
CTRADER_CLIENT_SECRET=your_new_secret
CTRADER_ACCOUNT_ID=9007390
```

---

### **3️⃣ OAuth Setup (Access Token megszerzése)**

**FONTOS:** Client ID és Secret önmagában NEM elég! Kell egy **Access Token** az OAuth flow-ból.

```bash
python ctrader_oauth_setup.py
```

**Mit fog csinálni:**
1. HTTP szerver indul (port 8080)
2. Böngészőben megnyílik a cTrader OAuth oldal
3. **Engedélyezd** a hozzáférést
4. Automatikusan létrejön a `credentials.json` ✅

**Replit-en:**
- A port 8080 automatikusan forward-olva lesz
- URL: `https://[replit-url]:8080`

---

### **4️⃣ Connection teszt**

Most már tesztelheted a kapcsolatot:

```bash
python test_ctrader_connection.py
```

**Várható kimenet:**

```
============================================================
🤖 cTrader API Connection Test
============================================================

📋 Credentials ellenőrzése...
✅ Client ID: 13619_O1bPSKUPi5...
✅ Client Secret: ********************
✅ Access Token: eyJhbGciOiJSUzI1...
✅ Account ID: 9007390

🔌 Kapcsolódás cTrader API-hoz...
📡 Credentials betöltése...
🌐 WebSocket kapcsolat...
✅ WebSocket kapcsolat sikeres!

📊 Account információk lekérése...
✅ Account info sikeresen lekérve!
   Balance: $10000.00
   Equity: $10000.00
   Currency: USD

📈 Market data teszt (XAUUSD)...
✅ Market data sikeresen lekérve!
   Symbol: XAUUSD
   Bid: 2650.50
   Ask: 2650.80
   Spread: 0.30

🔌 Kapcsolat bontása...
✅ Kapcsolat bezárva

============================================================
✅ cTrader API kapcsolat SIKERES!
============================================================

🎉 A bot készen áll a használatra!
```

---

### **5️⃣ Trading Bot indítása**

Ha a teszt sikeres volt:

```bash
# Állítsd be az Anthropic API kulcsot
export ANTHROPIC_API_KEY='your-anthropic-key'

# Indítsd el a botot
python ai_trading_advisor.py
```

**VAGY Admin UI-ból:**
1. Dashboard → **Start Bot** gomb

---

## 🐛 Hibaelhárítás

### ❌ "Access token hiányzik"

**Megoldás:**
```bash
python ctrader_oauth_setup.py
```

### ❌ "WebSocket connection failed"

**Lehetséges okok:**
1. Rossz credentials
2. Nincs internet kapcsolat
3. cTrader szerver leállás (ritka)

**Megoldás:**
1. Ellenőrizd a credentials-eket
2. Próbáld újra az OAuth-ot
3. Nézd meg a cTrader API status-t: https://status.spotware.com/

### ❌ "Invalid account ID"

**Megoldás:**
1. Ellenőrizd az Account ID-t a cTrader platformon
2. Demo account vs Live account - használd a megfelelőt

### ⚠️ "Market data hiba"

Ez **nem kritikus** - lehet hogy:
- Az adott szimbólum (XAUUSD) nem elérhető
- Demo account korlátozások
- Market zárva van (hétvége)

---

## 📊 Monitoring

### **Admin UI Dashboard:**

http://localhost:5000 (vagy Replit URL)

- ✅ Bot státusz
- 📊 Pozíciók
- 💰 P&L
- 📝 Trade history

### **Log fájlok:**

```bash
# Valós idejű naplók
tail -f trading_bot.log

# Admin UI naplók
http://localhost:5000/logs
```

---

## ✅ Sikerkritériumok

A bot működik, ha:

1. ✅ Connection test sikeres
2. ✅ Account info lekérve
3. ✅ Market data működik
4. ✅ Admin UI Dashboard mutatja a státuszt
5. ✅ Nincs kritikus hiba a logokban

---

## 🔒 Biztonsági checklist

- [ ] Új credentials generálva (ha megosztottad)
- [ ] `.env` fájl a `.gitignore`-ban
- [ ] `credentials.json` a `.gitignore`-ban
- [ ] Secrets nem commitolva GitHub-ra
- [ ] API kulcsok a Replit Secrets-ben (ha Replit-en fut)

---

## 📚 További dokumentáció

- [README.md](./README.md) - Fő dokumentáció
- [SETUP_GUIDE.md](./SETUP_GUIDE.md) - Setup lépések
- [CODESPACES_SETUP.md](./CODESPACES_SETUP.md) - Codespaces útmutató

---

**Készítette: Claude Code 🤖**

*Happy Testing! 🧪*
