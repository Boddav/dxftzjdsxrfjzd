---
name: Per-symbol weekend/market-hours gating for the trading loop
description: Why the bot must not run its decision loop for forex/metal/index symbols on weekends, and how crypto is exempt.
---

The trading bot's per-symbol decision loop (market data fetch + Claude call + trade execution) had no day/time gating at all — it ran every cycle (default 60s) for every configured symbol regardless of whether that market was open, including all weekend.

**Why:** Forex/metal/index CFDs are closed roughly Friday ~21:00 UTC through Sunday ~21:00 UTC; quotes are frozen/stale during that window. Running the full analysis+Claude pipeline anyway wastes API cost every cycle and risks decisions based on stale weekend data. Crypto (BTC/ETH) trades 24/7 and has no such window.

**How to apply:** `is_market_open(symbol)` in `ai_trading_advisor.py` (module-level, checks `RiskManager.is_crypto_symbol` first) gates the top of `_process_symbol` — closed-market symbols return immediately before any market-data/candle/Claude/position calls. Crypto symbols always pass. This does NOT affect the separate admin-dashboard price display path (`admin_interface.py`'s own `get_market_data` calls for the UI), which intentionally keeps showing last-known price regardless of market hours — only the trading *decision* loop is gated.
