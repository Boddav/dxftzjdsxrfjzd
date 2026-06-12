## 🚀 Deployment Útmutató - GitHub Pages + Backend

Ez az útmutató lépésről lépésre bemutatja, hogyan telepítsd az AI Trading Advisor-t GitHub Pages-re (frontend) és egy ingyenes backend szolgáltatásra.

---

## 📋 Áttekintés

**Architektúra:**
```
┌─────────────────────────────────────────┐
│   GitHub Pages (aiboddav.github.io)    │
│   - Statikus HTML/CSS/JS frontend       │
│   - Dashboard, Config, Logs             │
└──────────────┬──────────────────────────┘
               │ API calls (fetch)
               ↓
┌─────────────────────────────────────────┐
│   Backend API (Render/Railway/Heroku)  │
│   - Flask server (admin_interface.py)  │
│   - Trading bot logic                   │
│   - cTrader API integration             │
└─────────────────────────────────────────┘
```

---

## 1️⃣ GitHub Pages Setup (Frontend)

### Lépések:

1. **Repository Settings**
   ```
   GitHub repository → Settings → Pages
   ```

2. **Source beállítása**
   - Source: Deploy from a branch
   - Branch: `main` (vagy `claude/ai-trading-advisor-setup-*`)
   - Folder: `/docs`
   - Save

3. **Publikálás**
   - GitHub automatikusan deploy-olja
   - URL: `https://boddav.github.io/dxftzjdsxrfjzd/`
   - Vagy custom domain: `https://aiboddav.github.io` (ha repository neve: `aiboddav.github.io`)

4. **Ellenőrzés**
   - Várj 1-2 percet
   - Nyisd meg a GitHub Pages URL-t
   - Látnod kell a dashboard-ot

---

## 2️⃣ Backend Deployment Opciók

### Opció A: Render.com (Ajánlott - Ingyenes Tier)

#### Előnyök:
- ✅ Ingyenes tier elérhető
- ✅ Automatikus HTTPS
- ✅ GitHub integration
- ✅ Környezeti változók kezelése
- ✅ Logs viewing

#### Lépések:

1. **Regisztráció**
   - https://render.com/
   - Sign up GitHub accounttal

2. **New Web Service**
   - Dashboard → New → Web Service
   - Connect GitHub repository: `Boddav/dxftzjdsxrfjzd`

3. **Konfiguráció**
   ```
   Name: ai-trading-advisor
   Region: Frankfurt (vagy EU)
   Branch: main (vagy branch neved)
   Root Directory: (hagyld üresen)
   Runtime: Python 3
   Build Command: pip install -r requirements.txt
   Start Command: python admin_interface.py
   ```

4. **Environment Variables**
   ```
   ANTHROPIC_API_KEY=sk-ant-api03-...
   CTRADER_CLIENT_ID=13617_NoiIy...
   CTRADER_CLIENT_SECRET=M6qpm5h...
   CTRADER_ACCOUNT_ID=1234567
   SECRET_KEY=random-secret-key-here
   ADMIN_PORT=10000
   ```

5. **Deploy**
   - Create Web Service
   - Várj 2-3 percet a build-re
   - URL: `https://ai-trading-advisor.onrender.com`

6. **Frontend Konfiguráció**
   - Szerkeszd: `docs/js/config.js`
   ```javascript
   const API_CONFIG = {
       baseURL: 'https://ai-trading-advisor.onrender.com'
   };
   ```
   - Commit és push
   - GitHub Pages automatikusan frissül

---

### Opció B: Railway.app ($5/hó Ingyen Kredit)

#### Előnyök:
- ✅ $5 ingyen kredit havonta
- ✅ Gyors deployment
- ✅ Automatikus HTTPS
- ✅ Database support (ha később kell)

#### Lépések:

1. **Regisztráció**
   - https://railway.app/
   - Sign up GitHub accounttal

2. **New Project**
   - Dashboard → New Project
   - Deploy from GitHub repo
   - Válaszd ki: `Boddav/dxftzjdsxrfjzd`

3. **Environment Variables**
   - Settings → Variables
   - Add ugyanazokat mint Render-nél

4. **Start Command**
   - Settings → Deploy
   - Start Command: `python admin_interface.py`

5. **Domain**
   - Settings → Networking
   - Generate Domain
   - URL: `https://ai-trading-advisor.up.railway.app`

6. **Frontend Konfiguráció**
   - Frissítsd `docs/js/config.js` ugyanúgy

---

### Opció C: Heroku (Fizetős - $5/hó Eco Dyno)

#### Lépések:

1. **Heroku CLI Telepítés**
   ```bash
   # macOS
   brew tap heroku/brew && brew install heroku

   # Linux
   curl https://cli-assets.heroku.com/install.sh | sh
   ```

2. **Login és Create App**
   ```bash
   heroku login
   heroku create ai-trading-advisor
   ```

3. **Environment Variables**
   ```bash
   heroku config:set ANTHROPIC_API_KEY=sk-ant-...
   heroku config:set CTRADER_CLIENT_ID=13617_...
   heroku config:set CTRADER_CLIENT_SECRET=M6qpm5h...
   heroku config:set SECRET_KEY=random-secret
   ```

4. **Procfile létrehozása**
   ```bash
   echo "web: python admin_interface.py" > Procfile
   git add Procfile
   git commit -m "Add Procfile for Heroku"
   ```

5. **Deploy**
   ```bash
   git push heroku main
   ```

6. **URL**
   - `https://ai-trading-advisor.herokuapp.com`

---

## 3️⃣ cTrader OAuth Redirect URI Frissítése

**FONTOS:** Az OAuth redirect URI-t frissíteni kell a production backend URL-re!

### Lépések:

1. **cTrader Developer Portal**
   - https://ctrader.com/
   - My Apps → AI Trading Advisor

2. **Redirect URI hozzáadása**
   ```
   # Render példa:
   https://ai-trading-advisor.onrender.com/callback

   # Railway példa:
   https://ai-trading-advisor.up.railway.app/callback

   # Heroku példa:
   https://ai-trading-advisor.herokuapp.com/callback
   ```

3. **Mentés**
   - Save Changes

4. **OAuth Flow újrafuttatása**
   ```bash
   # A backend URL-en:
   https://ai-trading-advisor.onrender.com/

   # Vagy futtatd lokálisan és frissítsd a credentials.json-t:
   python ctrader_oauth_setup.py
   
   # Majd töltsd fel a backend-re (env vars-ként)
   ```

---

## 4️⃣ Production Checklist

### Backend Setup ✅

- [ ] Backend deploy-olva (Render/Railway/Heroku)
- [ ] Environment variables beállítva
- [ ] CORS engedélyezve GitHub Pages domain-hez
- [ ] Backend elérhető és válaszol
- [ ] `/api/status` endpoint működik

### Frontend Setup ✅

- [ ] GitHub Pages engedélyezve
- [ ] `docs/` folder publikálva
- [ ] `docs/js/config.js` frissítve backend URL-lel
- [ ] Frontend elérhető GitHub Pages URL-en
- [ ] Dashboard betöltődik
- [ ] API kapcsolat működik (zöld jelzés)

### cTrader Integration ✅

- [ ] OAuth redirect URI frissítve
- [ ] `credentials.json` létrehozva
- [ ] Access token érvényes
- [ ] API hívások működnek

### Security ✅

- [ ] `.env` NEM commitolva
- [ ] `credentials.json` NEM commitolva
- [ ] API kulcsok env vars-ban
- [ ] HTTPS mindenhol
- [ ] CORS csak engedélyezett domain-ekhez

---

## 5️⃣ Tesztelés

### 1. Frontend Elérése
```
https://boddav.github.io/dxftzjdsxrfjzd/
```

Ellenőrizd:
- [ ] Oldal betöltődik
- [ ] Nincs Console error
- [ ] "Kapcsolódva a backend API-hoz" zöld üzenet

### 2. API Tesztelés
```bash
# Státusz endpoint
curl https://ai-trading-advisor.onrender.com/api/status

# Válasz:
{"running": false, "last_update": null, ...}
```

### 3. Bot Indítása
- Frontend Dashboard → ▶ Indítás gomb
- Ellenőrizd a backend logs-ot
- Nézd a bot státuszt

---

## 6️⃣ Monitoring és Maintenance

### Backend Logs (Render példa)
```
Render Dashboard → ai-trading-advisor → Logs
```

### GitHub Pages Deploy Status
```
GitHub Repository → Actions → pages-build-deployment
```

### Automatikus Deployment
- **Frontend:** Minden commit a `main` branch-re → Auto deploy
- **Backend:** GitHub commit → Render auto deploy (ha engedélyezve)

---

## 🐛 Troubleshooting

### "Nincs kapcsolat a backend API-val"

**Ellenőrzés:**
1. Backend URL helyes a `config.js`-ben?
2. Backend fut és elérhető?
3. CORS engedélyezve a GitHub Pages domain-hez?
4. Network tab: CORS error?

**Megoldás:**
```javascript
// docs/js/config.js
const API_CONFIG = {
    baseURL: 'https://CORRECT-BACKEND-URL.com'  // ← Ellenőrizd!
};
```

### Backend "Application Error"

**Ellenőrzés:**
1. Environment variables beállítva?
2. Build sikeres volt?
3. Start command helyes?

**Megoldás:**
- Nézd a backend logs-ot
- Ellenőrizd az env vars-t
- Próbáld újra deploy-olni

### OAuth Redirect Error

**Probléma:**
```
redirect_uri_mismatch
```

**Megoldás:**
1. cTrader Developer Portal → Edit App
2. Add hozzá a pontos redirect URI-t:
   ```
   https://your-backend.onrender.com/callback
   ```
3. Futtasd újra az OAuth flow-t

---

## 📊 Költségek Összefoglalása

| Szolgáltatás | Költség | Limit |
|--------------|---------|-------|
| **GitHub Pages** | Ingyenes | Unlimited (public repo) |
| **Render Free Tier** | $0/hó | 750 óra/hó, auto-sleep |
| **Railway** | $5/hó kredit | ~100-200 óra futásidő |
| **Heroku Eco** | $5/hó | 1000 dyno óra/hó |

**Ajánlott kezdéshez:** GitHub Pages + Render Free Tier = **$0/hó**

---

## 🎉 Sikeres Deployment!

Ha minden lépést követtél:

✅ Frontend fut: `https://boddav.github.io/dxftzjdsxrfjzd/`
✅ Backend fut: `https://ai-trading-advisor.onrender.com`
✅ Bot indítható a webes felületről
✅ Mindenhol HTTPS

---

**Happy Trading! 🚀📈**
