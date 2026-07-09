---
name: Multi-broker cTrader OAuth and arbitrage engine safety
description: Design constraints for onboarding multiple demo cTrader broker accounts via one OAuth app and running a concurrent multi-connection arbitrage/trading engine safely.
---

- Multiple demo broker accounts can be onboarded through the SAME OAuth app: re-running the provider's authorize flow while logged into a different demo account yields a distinct token/account id. Bind the target account name to the flow via a server-side session nonce in the `state` param, and hard-fail on mismatch rather than silently falling back to a default identity.
  **Why:** a silent fallback on state mismatch defeats the CSRF/state protection the nonce exists for.

- Never persist a hardcoded "demo" flag for OAuth-derived credentials; resolve the actual account type from the provider and fail closed (treat as live/unsafe) if that lookup is ambiguous or fails.
  **Why:** a silently-defaulted safety flag can let a live account slip past downstream trading guards undetected.

- A background engine thread with its own event loop, exposed to sync web handlers, needs a lock around all shared mutable state, with snapshots deep-copied under that lock before serialization — otherwise concurrent mutation causes race conditions.

- Start/stop of a background engine thread must be serialized under a lifecycle lock, with stop() joining the thread before returning, and the loop's own stop-condition read from a lifecycle-local variable (not a shared field a concurrent start() could overwrite). Otherwise a fast stop+start can run two instances of the loop in parallel.
  **Why:** two concurrent loops polling/executing trades simultaneously is a correctness and trading-risk regression, not just a resource leak.

- For paired/hedged execution (e.g. arbitrage legs), open and close must use the identical price-diff direction/formula, and each leg's open/close call needs its own try/except/finally so per-leg completion state is never lost to an exception on the other leg.
