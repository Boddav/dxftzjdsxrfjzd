---
name: Flask bot in-memory state and restarts
description: A background trading/worker thread's running state must survive Flask process restarts, not just live in memory.
---

## In-memory `running` flags silently die on restart
A Flask app that tracks a long-running background thread (trading bot, worker loop, etc.) purely via an in-memory global (`bot_status['running']`) loses that state on any process restart — workflow restart, code redeploy, crash — without any error. The user only notices later because "nothing happened" (e.g. no trades placed), which looks like a business-logic bug rather than an infra one.
**Why:** Replit workflow restarts (including ones triggered by the agent itself while debugging unrelated code) kill and respawn the process; nothing preserves thread state across that boundary unless explicitly persisted.
**How to apply:** Persist the intended run state (running flag + relevant config like symbol list) to a small JSON file on start/stop, and on process startup check that file and auto-resume if it says the bot should be running. Also persist `running=false` when the worker thread exits on its own (error or natural stop), not just on the explicit stop endpoint — otherwise a crashed-and-not-restarted bot can wrongly auto-resume next boot. Guard the startup auto-resume call against Flask's debug-mode reloader double-invoking module-level code (check `WERKZEUG_RUN_MAIN` or `debug` flag), and wrap it in try/except so a resume failure never blocks the web server from coming up.
