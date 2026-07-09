---
name: Rendering raw LLM text in a dashboard
description: Safety rules when displaying AI-generated free text (reasoning, chat responses) in an admin/web UI.
---

## Never inject LLM output via innerHTML
Free-text output from an LLM (e.g. a "reasoning" field in a trading decision) is untrusted content, even though it comes from your own backend pipeline — the model could echo/produce HTML or script-like text (directly or via prompt injection from market/news data it was fed). Building table rows with template-literal `innerHTML` containing that text opens a stored XSS path in the admin UI.
**Why:** the field's content is model-generated, not fixed application text; only the surrounding template is safe.
**How to apply:** build DOM nodes with `document.createElement` and set `textContent` for any LLM-produced string, or otherwise escape it. This applies even for "just an internal dashboard" — it still executes in the admin's browser session.

## Atomic writes for a JSON file shared between a worker thread and web handlers
When a background thread periodically appends to and rewrites a small JSON state/log file (e.g. rolling list of recent decisions) that a web server's request handlers also read concurrently, write via a temp file + `os.replace()` (atomic rename) rather than truncating the original file in place, and guard the read-modify-write with a lock in the writer. Prevents readers from ever seeing a half-written/corrupt file.
