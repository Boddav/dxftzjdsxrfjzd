---
name: Shared JSON log needs a lock, not just atomic writes
description: Multiple in-process instances reading/writing the same JSON log file race even with atomic temp-file replace.
---

When several long-lived or short-lived object instances in the same process (e.g. a background trading loop's predictor vs. a fresh instance created per Flask request) each keep their own in-memory copy of a JSON-backed log and only occasionally save it, "last writer wins" data loss occurs — atomic file replace only protects against partial/corrupt writes, not against two writers overwriting each other's updates.

**Why:** In an ML-signal-quality tracker, both the live trading loop and an on-demand `/api/*` route each instantiated their own tracker object, loaded the log once at construction, and saved their own (possibly stale) copy back — silently dropping the other side's updates.

**How to apply:** For any JSON file written by more than one instance/thread, do NOT cache the parsed contents on the instance. Instead, wrap every mutation in a shared `threading.Lock`, and inside the lock: reload fresh from disk, mutate, then atomically write back. Never rely on an in-memory copy across calls when other instances can also write.
