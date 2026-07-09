---
name: AI-driven open-position management
description: How the bot lets Claude manage already-open positions (not just entries), and the safety rails around it.
---

The AI is given the open position(s) for the current symbol (with server-side unrealized P&L) in the SAME prompt/API call as the entry decision, and returns an optional `position_management` block (HOLD/CLOSE/MOVE_SL). This avoids doubling the (expensive) Claude API calls just to add position management.

**Why:** the user wanted more value per API call rather than only entry decisions, and wanted classic post-entry management (protecting profit, tightening stops, reacting to apparent news-driven moves).

**How to apply / key rules to preserve:**
- Position management must run BEFORE new-entry execution in the per-symbol cycle, so a same-cycle close+reopen isn't blocked by a stale open-position count.
- Any AI-issued MOVE_SL must be validated before sending to the broker: reject non-numeric values, reject if on the wrong side of a fresh bid/ask (fail-closed if price is missing), and reject if it would be *looser* than the existing stop (only risk-reducing changes allowed).
- cTrader's `ProtoOAExecutionType` success codes for amend/close include `4` (ORDER_REPLACED) in addition to `2/3/11` (ACCEPTED/FILLED/PARTIAL_FILL) — missing `4` makes successful SL/TP amends look like failures.
- The P&L recorded when the AI closes a position is a pre-close *unrealized* snapshot, not a guaranteed realized P&L (cTrader's close execution event doesn't return realized P&L directly).
