---
name: Multi-position AI response shape
description: An LLM asked for a per-open-position management decision may return a JSON array instead of a single object once there are 2+ positions on the same symbol.
---

When a prompt schema says "return this JSON object describing what to do with the open position," and the underlying symbol can have more than one open position at once (e.g. one BUY and one SELL hedge), the model will sometimes return a JSON **array** of one object per position instead of a single object — even if the schema wasn't written to expect that.

**Why:** the model is reasoning per-position and naturally generalizes the schema when there's more than one thing to decide about. This isn't a hallucination/error case to special-case away; it's a predictable shape variation once multi-position symbols enter the mix.

**How to apply:** every consumer of that field (execution logic, logging, dashboards) must normalize by checking `isinstance(x, list)` and iterating, rather than assuming a dict and calling `.get()` directly. Do this at every call site, not just the primary execution path — a lone unguarded `.get()` in a logging line is enough to crash the whole decision and silently fall back to a HOLD/error response.
