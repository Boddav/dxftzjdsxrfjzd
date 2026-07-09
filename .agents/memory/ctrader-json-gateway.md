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

## payloadType numbers must come from the real protobuf spec, not guessed
Several hand-typed `payloadType` constants (GetTrendbars, SubscribeSpots, etc.) were wrong, causing misleading `INVALID_REQUEST: Message missing required fields: <unrelated field>` errors — the gateway was parsing the payload as a *different* message type. Fix: `pip install ctrader-open-api` (official Spotware lib, unused for networking here, only for its generated protobuf classes) and read the true payloadType off `SomeProtoClass().payloadType`, and field names off `SomeProtoClass.DESCRIPTOR.fields_by_name.keys()`. Don't hand-guess these numbers/fields again.

## Push messages (spot events) interleave with request/response traffic
Once subscribed via `PROTO_OA_SUBSCRIBE_SPOTS_REQ`, the server pushes `ProtoOASpotEvent` (2131) asynchronously on the same socket, which can arrive between a request and its matching response. A naive single `send()`+`recv()` pairing breaks (grabs the wrong message). Fix: match responses by `clientMsgId` in a loop, caching/discarding non-matching push messages instead of treating them as errors.

## Trendbar (candle) OHLC is delta-encoded, not direct fields
`ProtoOATrendbar` has fields `low`, `deltaOpen`, `deltaHigh`, `deltaClose` (all raw units, /100000 for real price) — there are no direct `open`/`high`/`close` fields. Real price = `(low + deltaX) / 100000`. `utcTimestampInMinutes` is UTC — convert with `datetime.utcfromtimestamp`, not local-time `fromtimestamp`, or candle timestamps drift on non-UTC hosts.

## New-order response is a push event, not a request echo
After `PROTO_OA_NEW_ORDER_REQ`, the reply is a `PROTO_OA_EXECUTION_EVENT` (2126), never an echo of the request's payloadType — checking `response.payloadType == PROTO_OA_NEW_ORDER_REQ` is always false and misreports every accepted order as a failure. Judge success/failure from `payload.executionType` instead (ORDER_ACCEPTED=2, FILLED=3, PARTIAL_FILL=11 succeed; CANCELLED=5, EXPIRED=6, REJECTED=7, CANCEL_REJECTED=8 fail), and read the real failure reason from `payload.errorCode` (e.g. `NOT_ENOUGH_MONEY`), not a generic message.

## Architectural caveat (not yet fixed)
The request/response handling above is not concurrency-safe: two coroutines calling into the same `CTraderMCPServer` connection at once can steal each other's responses (`websockets` doesn't support concurrent `recv()`). Currently safe only because the bot's trading loop awaits everything sequentially in one coroutine chain — do not add parallel calls (e.g. concurrent per-symbol fetches) without first adding a single central reader task that dispatches by `clientMsgId`.

## Resource management
Each `CTraderMCPServer` instance holds one WebSocket; always call a `close()` on it after use (e.g. in a `finally` block) when opening a fresh connection per HTTP request, or connections/file descriptors leak under polling.
