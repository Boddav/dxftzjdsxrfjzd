---
name: Claude model choice for high-frequency loops
description: Cost lesson from a real incident where an expensive Claude model in a per-symbol trading loop burned API credit fast.
---

Do not use the top-tier/most-expensive Claude model (e.g. Opus tier) for a decision loop that fires per-symbol, every trading cycle. With 4 symbols and a ~1 minute cycle, that's ~150-240 calls/hour — at Opus pricing this drained $5→$1.36 of credit in about an hour.

**Why:** cost scales linearly with (symbols × cycles/hour), not with per-call complexity. A model tier that seems reasonable for one-off use becomes ruinous at that call volume.

**How to apply:** for any recurring/high-frequency LLM call, default to a mid-tier model (e.g. claude-sonnet-4-5) unless the user explicitly demands maximum reasoning quality and accepts the cost. Also make the cycle interval user-configurable with a sane minimum (we settled on 30s floor, 3600s ceiling) so users can trade off cost vs. responsiveness themselves.
