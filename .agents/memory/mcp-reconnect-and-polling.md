---
name: MCP connection self-healing and dashboard polling load
description: Why the bot's own cTrader connection never recovered from a keepalive drop, and why dashboard polling caused heavy API traffic.
---

The bot's long-lived `CTraderMCPServer.authenticated` flag only flips on explicit `connect()`/`close()` calls — a `keepalive ping timeout` websocket drop does NOT reset it. Checking `authenticated` alone to decide "is my connection usable" is unreliable; check the underlying websocket's `closed`/`close_code` state too, or every call after a silent drop repeats the same failure forever with no recovery.

**Why:** this caused the trading loop (and the dashboard reading positions through it) to go permanently dark after any transient network blip, requiring a manual restart to recover.

**How to apply:** after any await on a connection-bound call, if the error looks connection-related (keywords: connection/websocket/closed/keepalive/ping timeout, or ConnectionError/OSError/TimeoutError), close+reconnect immediately rather than waiting for a periodic health check — reconnect promptly, don't just detect at the end of a long cycle.

**Critical companion rule: don't swallow connection errors into empty-result fallbacks.** If a low-level fetch method (`get_positions`, `get_symbols_list`, etc.) catches ALL exceptions and returns `[]`/`{}` instead of re-raising, any reconnect-on-error logic further up the call chain never fires — the caller sees "call succeeded, no data" forever, not "call failed." This silently froze a shared connection dead after one keepalive drop until a full process restart. Methods that need retry/reconnect behavior from a caller must let connection-class exceptions propagate; only swallow exceptions at the outermost layer that actually decides what to do about them (log + reconnect, or return a user-facing error).

Also: don't resubscribe to spot/tick data on every poll of a shared/reused connection — track which symbol_ids are already subscribed (clear the set on close/reconnect) and only send `SUBSCRIBE_SPOTS_REQ` for new ones. Repeated resubscribing on frequent dashboard polling (e.g. every 5s) was a bigger driver of API traffic than the polling interval itself.

## Dashboard endpoints computing the same expensive live data must share one cache
When two separate endpoints (e.g. `/api/status` and `/api/positions`) both need the same live-fetched data (open positions) and are polled together by the frontend, give them a shared short-TTL cache (few seconds) instead of each calling the expensive fetch independently — otherwise every poll cycle does the real work twice.
**Why:** the underlying fetch went through a single-connection serializing lock (`run_shared`), so duplicate fetches didn't even run in parallel — they queued and doubled the latency on top of doubling API load.
**How to apply:** guard the whole "check TTL, then fetch-and-write" sequence with one `threading.Lock` (not just the read), and stamp the cache timestamp *after* the fetch completes so the TTL reflects actual freshness, not fetch-start time. This dedup is per-process only — irrelevant here (single dev-server process) but would need a cross-process store (e.g. Redis) under a multi-worker WSGI deployment.
