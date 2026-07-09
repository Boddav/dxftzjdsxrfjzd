---
name: Flask bot in-memory state and restarts
description: Bot run/stop state persistence, and shared MCP connection pattern for admin API endpoints.
---

Bot run/stop state must be persisted to disk and resumed on startup, or workflow restarts silently kill trading.

## Shared cTrader MCP connection for admin API endpoints
**Why:** Admin routes (`/api/positions`, `/api/test-position`) originally created a brand-new `CTraderMCPServer` and re-authenticated with cTrader on every single HTTP request, separate from the bot's own persistent connection. This caused excess WebSocket churn, `keepalive ping timeout` errors, and intermittent "no candle data" failures.

**How to apply:** `mcp_connection_manager.py` runs a dedicated background thread with its own asyncio event loop, holding one singleton `CTraderMCPServer` connection reused across requests (via `run_shared(async_func)`). Key details to preserve if touching this file:
- Flask routes are synchronous and run on their own thread(s); the shared connection lives on a separate loop, so all access goes through `asyncio.run_coroutine_threadsafe`, never by importing the loop object directly.
- Reconnect-on-failure is intentionally scoped to connection/auth-like errors only (`_looks_like_connection_error`) — business-logic errors (e.g. `NOT_ENOUGH_MONEY`) must NOT trigger a retry, since retrying a non-idempotent `place_order` could double-submit a trade.
- On timeout, the in-flight future is cancelled and the shared server is invalidated so a hung call doesn't block future requests.
- On a failed `connect()`, the partially-opened socket must be explicitly closed before discarding the server object, or the raw socket leaks.
