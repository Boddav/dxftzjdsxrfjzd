# 🔧 Spotware Open API Panel Setup

Részletes útmutató a cTrader OAuth alkalmazás beállításához.

---

## 📋 Előkövetelmények

- ✅ cTrader Demo vagy Live account
- ✅ Hozzáférés a Spotware Open API panelhez

---

## 🚀 1. lépés: Open API Panel megnyitása

**URL:** https://openapi.ctrader.com/

1. Jelentkezz be cTrader fiókkal
2. Menj: **"My Apps"** vagy **"Applications"**

---

## ➕ 2. lépés: Új alkalmazás létrehozása

### **A) Ha már van app-od (Client ID: 13619_...):**

1. Kattints az alkalmazásra
2. **Edit** vagy **Settings** gomb
3. Ugrás a **Redirect URIs** szekcióhoz

### **B) Ha nincs app, hozz létre újat:**

1. **"Create New Application"** gomb
2. Töltsd ki:
   ```
   Name: AI Trading Advisor
   Description: Automated trading bot with Claude AI
   ```
3. **Save** / **Create**

---

## 🔗 3. lépés: Redirect URI beállítása

Ez a **LEGFONTOSABB** lépés!

### **Replit környezetben:**

1. **Redirect URIs** szekció
2. **Add new URI** vagy **+** gomb
3. Írd be **PONTOSAN** (trailing slash nélkül):

```
https://h70xb.picard.replit.dev/callback
```

⚠️ **FONTOS:**
- `/callback` végződés **KÖTELEZŐ**
- Nincs trailing slash a végén
- HTTPS kell Replit-hez

### **Localhost fejlesztéshez:**

```
http://localhost:8080/callback
```

### **GitHub Codespaces-hez:**

```
https://{CODESPACE_NAME}-8080.app.github.dev/callback
```

Ahol `{CODESPACE_NAME}` a te egyedi Codespaces neved.

### **Windows Server / VPS:**

```
http://YOUR_SERVER_IP:8080/callback
```

---

## ✅ 4. lépés: Scope beállítása

**Scopes:**
- ✅ **`trading`** - Teljes hozzáférés (trade-ek végrehajtása) **← KELL!**
- 🔵 `accounts` - Csak olvasás (opcionális)

**Hogyan:**
1. **Scopes** szekció
2. Pipáld ki: **trading**
3. **Save**

---

## 🔑 5. lépés: Credentials másolása

### **Client ID és Secret:**

1. **Client ID:** `13619_O1bPSKUPi5g...` (látható)
2. **Client Secret:** Kattints **"Show Secret"** vagy **"Regenerate"**
3. **Másold ki mindkettőt**

⚠️ **BIZTONSÁGI FIGYELMEZTETÉS:**
- Secret csak egyszer látható generálás után
- Tárold biztonságosan (pl. Replit Secrets)
- NE commitoldd GitHub-ra!

---

## 📝 6. lépés: Credentials beállítása a bot-ban

### **A) Replit Secrets (AJÁNLOTT):**

1. Replit bal menü → **Secrets** (🔒 zár ikon)
2. Add hozzá:

```
CTRADER_CLIENT_ID = 13619_O1bPSKUPi5g...
CTRADER_CLIENT_SECRET = 50FEJJFWDB...
CTRADER_ACCOUNT_ID = 9007390
```

### **B) .env fájl (alternatíva):**

```bash
CTRADER_CLIENT_ID=13619_O1bPSKUPi5g...
CTRADER_CLIENT_SECRET=50FEJJFWDB...
CTRADER_ACCOUNT_ID=9007390
```

### **C) Admin UI:**

1. Nyisd meg: http://localhost:5000
2. **Beállítások** → Töltsd ki a mezőket
3. **Mentés**

---

## 🧪 7. lépés: OAuth flow tesztelése

```bash
python ctrader_oauth_setup.py
```

**Mit fogsz látni:**

1. **Konzolban:**
```
🔐 Redirect URI: https://h70xb.picard.replit.dev/callback
🌐 Auth URL: https://id.ctrader.com/my/settings/openapi/grantingaccess/?client_id=...
🚀 OAuth szerver elindult!
👉 Nyisd meg böngészőben: https://h70xb.picard.replit.dev
```

2. **Böngésző automatikusan megnyílik**

3. **cTrader OAuth oldal:**
   - Jelentkezz be (ha kell)
   - **"Grant Access"** vagy **"Engedélyezés"** gomb

4. **Redirect vissza az app-hoz:**
   - "✅ Sikeres Csatlakozás!"
   - `credentials.json` létrejön

---

## ❌ Gyakori hibák

### **1. "OAuth hiba: 'access_token'"**

**OK:** Redirect URI nem egyezik

**Megoldás:**
1. Ellenőrizd a Spotware panelben a Redirect URI-t
2. Pontosan egyezzen: `https://h70xb.picard.replit.dev/callback`
3. Nincs extra `/` vagy szóköz

### **2. "Invalid redirect_uri"**

**OK:** Redirect URI nincs regisztrálva

**Megoldás:**
1. Menj Spotware panelbe
2. Add hozzá a Redirect URI-t
3. **Save**
4. Próbáld újra

### **3. "Invalid client_id or client_secret"**

**OK:** Rossz credentials

**Megoldás:**
1. Ellenőrizd a Client ID-t és Secret-et
2. Regenerálj új Secret-et (ha kell)
3. Frissítsd a bot-ban

### **4. "Authorization expired"**

**OK:** Túl sokáig vártál az engedélyezéssel

**Megoldás:**
- Indítsd újra az OAuth flow-t
- Gyorsabban kattints az "Engedélyezés" gombra

---

## 🔍 Debug információk

### **Nézd meg a Python konzol logokat:**

```
INFO - 🔐 Redirect URI: https://h70xb.picard.replit.dev/callback
INFO - 🌐 Auth URL: https://id.ctrader.com/my/settings/openapi/grantingaccess/?client_id=...
INFO - ✅ Authorization code kapva: abc123...
INFO - 🔄 Token csere folyamatban...
INFO - Response status: 200
INFO - Token response keys: ['access_token', 'refresh_token']
INFO - ✅ Access token kapva!
```

### **Ha hibát látsz:**

```
ERROR - ❌ Token csere hiba: Invalid redirect_uri
```

Akkor nézd meg a fenti "Gyakori hibák" szekciót.

---

## 📊 Sikerkritériumok

✅ OAuth flow sikeresen lefutott  
✅ `credentials.json` fájl létrejött  
✅ Nincs hiba a konzolban  
✅ Böngészőben: "✅ Sikeres Csatlakozás!"  

---

## 🔒 Biztonsági best practices

### **DO:**
- ✅ Tárold a Secret-et Replit Secrets-ben vagy környezeti változóban
- ✅ `.gitignore`-ban: `.env`, `credentials.json`
- ✅ Használj HTTPS-t production-ben
- ✅ Regenerálj Secret-et ha nyilvánosságra került

### **DON'T:**
- ❌ Ne commitold a Client Secret-et GitHub-ra
- ❌ Ne oszd meg publikusan (chat, email, stb.)
- ❌ Ne használj HTTP-t production-ben (csak localhost-on OK)

---

## 📚 További információk

**Official Documentation:**
- cTrader Open API: https://help.ctrader.com/open-api/
- OAuth 2.0 flow: https://help.ctrader.com/open-api/authentication/

**API Endpoints:**
- Auth: `https://id.ctrader.com/my/settings/openapi/grantingaccess/`
- Token: `https://openapi.ctrader.com/apps/token`
- Accounts: `https://openapi.ctrader.com/apps/accounts`

**Supported Scopes:**
- `trading` - Full access (trade execution)
- `accounts` - Read-only access

---

## ✅ Checklist

Használd ezt a checklistet a setup során:

- [ ] cTrader account létrehozva (Demo vagy Live)
- [ ] Spotware Open API panel megnyitva: https://openapi.ctrader.com/
- [ ] Új app létrehozva VAGY meglévő megnyitva
- [ ] Redirect URI hozzáadva: `https://h70xb.picard.replit.dev/callback`
- [ ] Scope: `trading` engedélyezve
- [ ] Client ID és Secret kimásolva
- [ ] Credentials beállítva (Replit Secrets / .env / Admin UI)
- [ ] OAuth flow tesztelve: `python ctrader_oauth_setup.py`
- [ ] `credentials.json` létrejött
- [ ] Connection test sikeres: `python test_ctrader_connection.py`

---

**Készítette: Claude Code 🤖**

*Happy Trading! 📈*
