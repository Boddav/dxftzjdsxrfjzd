---
name: Stabilizing the Claude trading-decision JSON contract
description: Concrete techniques used to stop the "position_management sometimes object, sometimes array, sometimes missing" parser fragility.
---

A per-symbol trading-decision prompt/response contract is parsed by multiple consumers (execution + logging), so shape drift in the LLM's JSON output is a recurring fragility source, not a one-off bug.

**Why:** letting the model omit a field or return either an object or array for the same field (depending on whether zero/one/many items apply) forces every consumer to defensively branch on `isinstance(..., list)` forever, and any consumer that forgets to branch breaks silently.

**How to apply (the fix, generalizable to any per-symbol/per-item JSON-contract prompt):**
1. Never let the schema be "sometimes present, sometimes omitted, sometimes singular" — collapse it to always the same type (e.g. `position_management` is now always a JSON array, `[]` when there's nothing to report), and say so explicitly in the prompt.
2. State the JSON-only constraint explicitly and literally ("no markdown code fences, no other text") even though the code already strips ```json fences defensively — the explicit instruction reduces how often the fence-wrapped case happens at all.
3. Give 1-2 concrete worked examples of the exact response shape (illustrative values) directly in the prompt — this measurably stabilizes small JSON contracts more than prose schema descriptions alone.
4. Disambiguate any field whose unit is unclear from its name (e.g. `new_stop_loss` — is it a price or a pip offset?) with an explicit units note in the schema description itself.
5. Use `temperature=0` for structured-output prompts where you want format stability over creative variance, and size `max_tokens` to the expected structured payload rather than leaving generous defaults.
6. Keep two separate confidence gates distinct on purpose: a prompt-level instruction ("if uncertain, HOLD with confidence 0.0") shapes the model's own self-assessment, while a hardcoded numeric threshold in the calling code (e.g. `MIN_TRADE_CONFIDENCE`) is the actual enforced gate — don't rely on the prompt instruction alone to prevent low-conviction trades.
