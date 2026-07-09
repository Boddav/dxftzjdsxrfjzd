---
name: cTrader Open API JSON gateway quirks
description: Non-obvious protocol details for connecting to cTrader's Open API over the WebSocket JSON gateway (wss://demo.ctraderapi.com:5036 / live.ctraderapi.com:5036) rather than the raw protobuf TCP socket.
---

## Account ID confusion
The `accountId` used for `PROTO_OA_ACCOUNT_AUTH_REQ` (`ctidTraderAccountId`) is **not** the trader login number shown in the cTrader platform/broker UI. It's an internal ID.
**How to apply:** After OAuth, call `PROTO_OA_GET_ACCOUNTS_BY_ACCESS_TOKEN_REQ` (payloadType 2149) with the access token — the response's `ctidTraderAccount[].ctidTraderAccountId` is the value to use, not `traderLogin`. Using the login number gives `CH_CTID_TRADER_ACCOUNT_NOT_FOUND`.

## Order placement required fields
`PROTO_OA_NEW_ORDER_REQ` (2106) fails with `INVALID_REQUEST: Message missing required fields: executionType` unless `timeInForce` (e.g. `"IMMEDIATE_OR_CANCEL"`) is included, even though `executionType` isn't a request field — it's a misleading error description on this gateway.
**Why:** the JSON gateway's error message names the wrong field; the actual fix is adding `timeInForce`.

## Volume units
Order `volume` is in centiunits: `volume = lots * 10,000,000` (e.g. 0.01 lot = 100,000). Minimum volume is broker/symbol-dependent (observed minimum ~1000 raw = 0.0001 lot scale differs per symbol) — the server returns `TRADING_BAD_VOLUME` with the actual minimum if too low.

## Position price field
In `PROTO_OA_RECONCILE_RES` positions, `position.price` is already a real decimal price (e.g. `1.14148`), not scaled by 100000 like tick data — do not double-normalize it.

## Order response payloadType
On this JSON gateway, a successful order execution response reuses the same `payloadType` as `PROTO_OA_NEW_ORDER_REQ` (2126) rather than a distinct execution-event type — disambiguate success by checking for an `order`/`position` key in the payload, not by payloadType alone.

## Resource management
Each `CTraderMCPServer` instance holds one WebSocket; always call a `close()` on it after use (e.g. in a `finally` block) when opening a fresh connection per HTTP request, or connections/file descriptors leak under polling.
