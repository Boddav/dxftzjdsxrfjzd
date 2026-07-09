---
name: MCP connection self-healing and dashboard polling load
description: Why the bot's own cTrader connection never recovered from a keepalive drop, and why dashboard polling caused heavy API traffic.
---

The bot's long-lived `CTraderMCPServer.authenticated` flag only flips on explicit `connect()`/`close()` calls — a `keepalive ping timeout` websocket drop does NOT reset it. Checking `authenticated` alone to decide "is my connection usable" is unreliable; check the underlying websocket's `closed`/`close_code` state too, or every call after a silent drop repeats the same failure forever with no recovery.

**Why:** this caused the trading loop (and the dashboard reading positions through it) to go permanently dark after any transient network blip, requiring a manual restart to recover.

**How to apply:** after any await on a connection-bound call, if the error looks connection-related (keywords: connection/websocket/closed/keepalive/ping timeout, or ConnectionError/OSError/TimeoutError), close+reconnect immediately rather than waiting for a periodic health check — reconnect promptly, don't just detect at the end of a long cycle.

Also: don't resubscribe to spot/tick data on every poll of a shared/reused connection — track which symbol_ids are already subscribed (clear the set on close/reconnect) and only send `SUBSCRIBE_SPOTS_REQ` for new ones. Repeated resubscribing on frequent dashboard polling (e.g. every 5s) was a bigger driver of API traffic than the polling interval itself.
