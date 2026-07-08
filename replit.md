# AI Trading Advisor

Claude AI alapú automatizált trading bot cTrader API-val, web admin felülettel.

## Stack

- **Backend**: Python / Flask (port 5000)
- **AI**: Anthropic Claude (via `anthropic` SDK)
- **Trading API**: cTrader Open API (WebSocket)
- **MCP**: Model Context Protocol szerver a strukturált AI eszközökhöz

## Futtatás

```bash
python admin_interface.py
```

A workflow neve: **Start application** — automatikusan indul.

## Belépési pontok

| Fájl | Szerepe |
|---|---|
| `admin_interface.py` | Flask web admin felület (port 5000) |
| `ai_trading_advisor.py` | Fő trading bot logika |
| `mcp_server.py` | MCP szerver – cTrader eszközök |
| `ctrader_oauth_setup.py` | cTrader OAuth flow (egyszeri beállítás) |

## Szükséges secrets / env vars

| Változó | Hol állítható be | Megjegyzés |
|---|---|---|
| `ANTHROPIC_API_KEY` | Replit Secrets | ✅ Beállítva |
| `SESSION_SECRET` | Replit Secrets | ✅ Beállítva |
| `CTRADER_CLIENT_ID` | Replit Secrets | cTrader OAuth után szükséges |
| `CTRADER_CLIENT_SECRET` | Replit Secrets | cTrader OAuth után szükséges |
| `CTRADER_ACCOUNT_ID` | Replit Secrets | cTrader account ID |

## cTrader Csatlakozás

A bot futtatásához cTrader OAuth szükséges:

```bash
python ctrader_oauth_setup.py
```

Ez létrehoz egy `credentials.json` fájlt és beállítja a szükséges env varokat.

## User preferences

- Magyar dokumentáció és UI
