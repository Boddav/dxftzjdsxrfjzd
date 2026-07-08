# 🚀 GitHub Codespaces Setup Útmutató

**AI Trading Advisor** projektet GitHub Codespaces-ben történő használatához.

---

## 📋 Előkészületek

1. **GitHub Account** - Szükséges Codespaces használatához
2. **Anthropic API Kulcs** - [Szerezd be itt](https://console.anthropic.com/)
3. **cTrader Account** - Demo vagy Live (ajánlott: demo)

---

## 🎯 1. Codespaces Indítása

### GitHub Repository-ból:

1. Menj a repository oldalára GitHub-on
2. Kattints a **Code** gombra (zöld)
3. Válaszd ki a **Codespaces** fület
4. Kattints: **Create codespace on [branch-name]**

Várj 1-2 percet, amíg a Codespaces betöltődik.

---

## ⚙️ 2. Automatikus Setup

A Codespaces indításakor **automatikusan települnek** a függőségek:

```bash
# Ez automatikusan lefut a postCreateCommand révén:
pip install --upgrade pip
pip install -r requirements.txt
```

### Manuális setup (ha szükséges):

```bash
bash .devcontainer/setup.sh
```

---

## 🔑 3. API Kulcsok Beállítása

### A) Anthropic API Kulcs

**Terminálban:**
```bash
export ANTHROPIC_API_KEY='your-api-key-here'
```

**VAGY szerkeszd a `.env` fájlt:**
```bash
# .env fájl
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

### B) cTrader OAuth Setup

```bash
python3 ctrader_oauth_setup.py
```

**Mit fog ez csinálni:**
1. HTTP szerver indul a **port 8080-on**
2. Codespaces automatikusan ad egy **publikus URL-t**
3. Böngészőben megnyílik a cTrader OAuth oldal
4. Engedélyezd a hozzáférést ✅
5. Automatikusan létrejön a `credentials.json` ✅

---

## 🌐 4. Portok Megnyitása

GitHub Codespaces automatikusan forward-olja a portokat:

| Port | Szolgáltatás | URL |
|------|-------------|-----|
| **5000** | Admin UI | `https://{codespace}-5000.app.github.dev` |
| **8080** | OAuth Server | `https://{codespace}-8080.app.github.dev` |

### Hogyan érd el:

1. **VS Code alsó sávban**: Kattints a **PORTS** fülre
2. Keresd meg a **5000** vagy **8080** portot
3. Kattints rá jobbgombbal → **"Open in Browser"**

**VAGY** egyszerűen kattints a port melletti **🌐 ikon**ra.

---

## 🖥️ 5. Admin Felület Indítása

```bash
python3 admin_interface.py
```

**Kimenet:**
```
╔════════════════════════════════════════════╗
║   AI Trading Advisor - Admin Interface    ║
╚════════════════════════════════════════════╝

🌐 Admin felület: http://localhost:5000
```

**Nyisd meg böngészőben:**
- Codespaces: `https://{codespace}-5000.app.github.dev`
- Helyi: `http://localhost:5000`

---

## 🤖 6. Trading Bot Indítása

### A) Admin UI-ból (Ajánlott)

1. Nyisd meg az Admin felületet: `http://localhost:5000`
2. Menj: **Beállítások** → Állítsd be az API kulcsokat
3. Kattints: **Start Bot** ▶️

### B) Terminálból (Direkt)

```bash
python3 ai_trading_advisor.py
```

**Kimenet:**
```
============================================================
🤖 AI Trading Advisor - Claude AI + cTrader
============================================================

✅ Minden rendben, bot indítása...
🚀 Trading bot indítása...
🤖 AI Trading Advisor inicializálva
✅ Csatlakozva a cTrader API-hoz
💰 Számla: $10000.00
```

---

## 🛠️ 7. Gyakori Hibák & Megoldások

### ❌ "Port 5000 already in use"

```bash
# Állítsd le a futó szervert
lsof -ti:5000 | xargs kill -9

# Vagy használj másik portot
ADMIN_PORT=5001 python3 admin_interface.py
```

### ❌ "ANTHROPIC_API_KEY not found"

```bash
# Export environment variable
export ANTHROPIC_API_KEY='your-api-key'

# VAGY .env fájl létrehozása
echo "ANTHROPIC_API_KEY=your-api-key" >> .env
```

### ❌ "credentials.json not found"

```bash
# Futtasd újra az OAuth setup-ot
python3 ctrader_oauth_setup.py
```

### ❌ Codespaces URL nem nyílik meg

1. **PORTS** fül → Keress a **5000** portot
2. Állítsd **Public**-ra a visibility-t
3. Jobbklikk → **"Open in Browser"**

---

## 📊 8. Monitoring & Naplók

### Admin UI Naplók

1. Nyisd meg: `http://localhost:5000`
2. Menj: **Logs** fül
3. Szűrés: INFO / WARNING / ERROR

### Terminál Naplók

```bash
# Részletes logolás
export LOG_LEVEL=DEBUG
python3 ai_trading_advisor.py

# Log file-ba mentés
python3 ai_trading_advisor.py 2>&1 | tee trading.log
```

---

## 🔒 9. Biztonsági Best Practices

### ⚠️ FONTOS

- ❌ **SOHA ne commitolj credentials.json-t**
- ❌ **SOHA ne commitolj .env fájlt API kulcsokkal**
- ✅ **Használd a .gitignore-t** (már konfigurálva)
- ✅ **Először demo accounton tesztelj**

### .gitignore ellenőrzése

```bash
cat .gitignore
```

**Biztosítsd, hogy ezek benne legyenek:**
```
credentials.json
.env
*.log
__pycache__/
```

---

## 🚦 10. Gyors Parancsok Összefoglaló

```bash
# Setup
bash .devcontainer/setup.sh

# Admin UI
python3 admin_interface.py

# OAuth Setup
python3 ctrader_oauth_setup.py

# Trading Bot
python3 ai_trading_advisor.py

# Naplók
tail -f trading.log

# Port ellenőrzés
lsof -i:5000
lsof -i:8080
```

---

## 📚 11. További Dokumentáció

- [README.md](./README.md) - Fő dokumentáció
- [SETUP_GUIDE.md](./SETUP_GUIDE.md) - Részletes setup útmutató
- [DEPLOYMENT.md](./DEPLOYMENT.md) - Deployment útmutató

---

## 🆘 Támogatás

Ha elakadsz:

1. Nézd meg a [Hibaelhárítás](#7-gyakori-hibák--megoldások) szekciót
2. Ellenőrizd a logokat
3. Nyiss egy GitHub Issue-t

---

**Készítette: Claude Code 🤖**

*Happy Trading in Codespaces! 🚀*
