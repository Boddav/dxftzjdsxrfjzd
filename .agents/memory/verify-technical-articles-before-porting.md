---
name: Verify trading/technical articles contain a real algorithm before porting
description: financial-hacker.com and similar trading blogs often publish commentary/review pieces about commercial systems, not the actual algorithm — check before offering a time estimate or building anything.
---

When a user links an article and asks to implement "this system," fetch and read the actual article content first, not just the title/URL. Some articles (e.g. financial-hacker.com pieces about Robert Pardo's "Ranger"/RangerZ) are journalistic/opinion pieces describing a commercial, closed-source product's philosophy and portfolio-construction approach, with no publishable formula, pseudocode, or entry/exit rules — only a high-level description (e.g. "starts from a classic Donchian/Turtle range breakout, then adds many switches: trend/counter-trend, volatility filters, stop/limit entries, trailing stops").

**Why:** Giving a confident time estimate or building "the Ranger system" from such an article would mean inventing rules and passing them off as the real, named system — which is misleading to the user and violates the no-mocked-functionality principle. The user should be told explicitly that no concrete algorithm exists in the source before any estimate or implementation is offered.

**How to apply:** Before estimating effort or writing code for "implement this trading system from this article," fetch the article and confirm it contains an actual rule set/formula/pseudocode. If it doesn't, tell the user directly and offer a named, real, implementable alternative (e.g. a classic Donchian breakout) instead of fabricating one under the original system's name.
