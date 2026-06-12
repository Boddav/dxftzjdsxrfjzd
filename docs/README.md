# AI Trading Advisor - Web Interface

Ez a mappa tartalmazza az AI Trading Advisor statikus frontend alkalmazását, amely GitHub Pages-en fut.

## 🌐 Live Site

**URL:** https://boddav.github.io/dxftzjdsxrfjzd/

## 📂 Struktúra

```
docs/
├── index.html          # Dashboard oldal
├── config.html         # Beállítások
├── logs.html           # Naplók
├── css/
│   └── style.css       # Stílusok
└── js/
    ├── config.js       # API konfiguráció
    ├── dashboard.js    # Dashboard logika
    ├── config-page.js  # Config oldal logika
    └── logs.js         # Logs oldal logika
```

## ⚙️ Konfiguráció

### Backend API URL Beállítása

Szerkeszd a `js/config.js` fájlt:

```javascript
const API_CONFIG = {
    baseURL: 'https://your-backend-api.onrender.com'
};
```

Cseréld ki a `your-backend-api.onrender.com` részt a saját backend URL-edre.

## 🚀 Deployment

A GitHub Pages automatikusan deploy-olja ezt a mappát minden commit után.

1. Commit és push
2. GitHub Actions lefuttatja a deploy-t
3. ~1-2 perc múlva elérhető az új verzió

## 🔗 Hasznos Linkek

- [Backend Deployment Útmutató](../DEPLOYMENT.md)
- [Fő README](../README.md)
- [GitHub Repository](https://github.com/Boddav/dxftzjdsxrfjzd)
