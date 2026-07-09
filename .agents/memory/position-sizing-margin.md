---
name: Risk-based position sizing must be margin-aware
description: Why bot-submitted trades got NOT_ENOUGH_MONEY while the manual Test button always worked, and the fix.
---

Risk-based lot sizing (risk % of balance ÷ stop-loss distance) alone is not enough — it must also be capped by available margin, or high-notional symbols (e.g. XAUUSD, ~$400k/lot) can compute a lot size the account can't afford, even though the risk-per-trade % looks conservative.

**Why:** The manual "Test" button always used a small fixed lot size, so it never hit this; only the bot's risk-based sizing did, which made the bug look like a bot-only issue (misleadingly pointing at "the lot calculation" rather than "missing margin check").

**How to apply:** `RiskManager.calculate_position_size` in `ai_trading_advisor.py` takes `min(risk_based_lots, margin_based_lots)`, where margin_based_lots is derived from `(balance * MARGIN_SAFETY_FACTOR - used_margin) / (price * contract_size / leverage)`. cTrader's Open API does not expose account/symbol leverage directly, so leverage is a configurable assumption (`CTRADER_LEVERAGE` env var, default 100) — revisit if the actual account leverage is known.

Also: a `HARD_MAX_RISK_PER_TRADE` clamp (5%) exists in code because config-driven risk % was previously silently ignored (hardcoded default masked it); when wiring config values to actually take effect, check for stale/unsafe values already sitting in config that were never actually applied.

When estimating margin used by already-open positions, never fall back to "assume same symbol as the one currently being sized" for unresolved symbol IDs — a forex position misclassified as gold (or vice versa) skews estimated margin by orders of magnitude. Fall back to the largest known contract size (worst case) instead.
