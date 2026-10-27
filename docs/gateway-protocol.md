<!-- github-only -->
<table><tr>
<td align="center"><b>Docs</b></td>
<td align="center"><a href="market/index.md">Market</a></td>
<td align="center"><a href="earn/index.md">Earn</a></td>
<td align="center"><a href="wallet/index.md">Wallet</a></td>
<td align="center"><a href="report/index.md">Report</a></td>
<td align="center"><a href="reference/index.md">Reference</a></td>
<td align="center"><a href="https://tribulnation.com/sdk/docs/support">Support matrix</a></td>
</tr></table>
<!-- /github-only -->

# Gateway wire protocol

This page specifies what the [SDK gateway](gateway.md) and its clients exchange, so a
client in any language can speak it. `ProxySDK` is the reference client and
`tribulnation.sdk.gateway.codec` the reference codec. The machine-readable form is the
JSON Schema [gateway-protocol.schema.json](https://github.com/tribulnation/sdk/blob/main/docs/gateway-protocol.schema.json).

## Transport and handshake

1. The gateway serves one WebSocket endpoint at path `/`, on a Unix socket (`tn gateway`)
   or any listener an embedding application binds. One connection carries any number of
   concurrent calls and streams.
2. Every message is one **binary** frame holding one UTF-8 JSON object. Text frames are
   ignored.
3. The client offers the subprotocol `tribulnation-gateway.v2` in
   `Sec-WebSocket-Protocol`, and the gateway selects it.
   1. A client offering subprotocols that do not include the gateway's version is refused
      with HTTP 400 before the upgrade, and the gateway logs the mismatch.
   2. A client that receives a different subprotocol, or a refused upgrade, fails the
      connection (`ProxySDK` raises `GatewayError`).
   3. A peer that names no subprotocol predates negotiation (SDK 2.17 and earlier) and
      speaks v1, so it is refused like any other v1 peer.
   4. v2 (SDK 3.0, ADR 0051) splits spot from margin requests: `position`,
      `available_notional`, `collateral` and `collateral_id` address margin (perpetual)
      markets only, spot markets answer `balances`, and spot `rules` replies carry `base`
      and `quote`.
4. The version changes only when a frame stops meaning the same thing to a peer of the
   previous version: a removed or renamed field or kind, a changed value encoding, or a
   new required field. Adding an optional field or a reply field is not a version
   change, because decoders ignore unknown fields. A new message kind is a version change
   for the side that must decode it.

## Envelope

Every frame is an object with:

| Field | Type | Meaning |
|---|---|---|
| `tag` | string | Message kind, listed below. Requests and replies share most tags. |
| `id` | string | Correlation ID chosen by the client (a UUID in `ProxySDK`). |

The remaining fields depend on the kind. Field order is not significant.

1. **Calls.** The client sends a request with a fresh `id`. The gateway answers exactly
   once with the reply kind of the same `id`, or with `err`. Replies may arrive in any
   order.
2. **Streams.** The client sends `depth_stream` or `trades_stream` with a fresh `id`.
   The gateway sends `depth_data` or `trades_data` items with that `id` until the
   stream ends, then one `end`. The client stops a stream with `unsub` carrying the
   stream's `id`; no `end` follows a cancelled stream.
3. A connection drop ends every call and stream on it. Nothing is replayed after a
   reconnect.

## Values

| Type | Encoding |
|---|---|
| Decimal (prices, quantities, rates, amounts) | JSON string with the exact decimal text, e.g. `"0.015"`. Decoders also accept JSON numbers. |
| Time | RFC 3339 string. Times the SDK produces are UTC, written with `Z`, e.g. `"2026-10-19T12:30:00.123456Z"`; other offsets are kept as given. |
| Duration | ISO 8601 duration. Written in seconds (`"PT28800S"`); any ISO 8601 form (`"PT8H"`) is accepted. |
| Optional value | `null` when absent. Optional request fields may be omitted. |
| `settings` | Object of venue name to an object of that venue's settings, e.g. `{"dydx": {"good_til_blocks": 20}}`. The gateway passes it to the venue adapter, which validates its own entry. Defaults to `{}`. |
| `details`, `result` | Venue-specific JSON, carried as is. Clients must not depend on its shape across venues. |

Domain objects (`Book`, `Trade`, `Rules`, `OrderState`, ...) are JSON objects with the
fields of the SDK types of the same name, documented in [Types](market/types.md) and
defined in the schema. Two of them need care:

1. `Book.bids` and `Book.asks` are lists of `{"price", "qty"}`. Bids are sorted best
   (highest) first and asks best (lowest) first.
2. A `collateral` reply's `collateral` is a `PerpCollateral` when it carries
   `initial_margin`, `maintenance_margin`, `leverage` and `margin_mode`, and a plain
   `Collateral` (`equity`, `free_collateral`) otherwise.
3. A `rules` reply's `rules` is a `SpotRules` when it carries `base` and `quote`, and a
   plain `Rules` otherwise.

## Requests

A request's reply has the same tag, except `exchange_collateral` (answered by
`collateral`) and `exchange_perp_collateral` (answered by `perp_collateral`). Market
requests address a market as `<account_id>:<exchange_id>:<market_id>`, e.g.
`hl:perp:BTC`; exchange requests address it as `account_id` plus `exchange_id`.

| `tag` | Fields | Purpose |
|---|---|---|
| `venues` | none | List the gateway's account keys. |
| `venue` | `account_id` | Resolve the venue behind an account key. |
| `exchanges` | `account_id` | List a venue's exchanges. |
| `exchange` | `account_id`, `exchange_id` | Resolve an exchange's product type and venue. |
| `markets` | `account_id`, `exchange_id` | List an exchange's market IDs. |
| `tickers` | `account_id`, `exchange_id`, `markets`?, `settings`?, `ttl`? | Fetch bulk tickers. |
| `perp_stats` | `account_id`, `exchange_id`, `markets`?, `settings`?, `ttl`? | Fetch bulk perpetual statistics. |
| `exchange_collateral` | `account_id`, `exchange_id`, `ttl`? | Fetch a perpetual exchange's pool as generic collateral. |
| `balance` | `account_id`, `exchange_id`, `asset`, `ttl`? | Fetch one asset's balance on a spot exchange. |
| `exchange_perp_collateral` | `account_id`, `exchange_id`, `ttl`? | Fetch a perpetual exchange's margin bucket. |
| `depth` | `market_id`, `levels`?, `settings`? | Fetch one order book snapshot. |
| `rules` | `market_id`, `refetch`? | Fetch trading rules. |
| `fees` | `market_id`, `refetch`? | Fetch account-specific trading fees. |
| `leverage` | `market_id`, `ttl`? | Fetch the account's leverage on a perpetual market. |
| `candles` | `market_id`, `interval`, `start`, `end` | Fetch candles in a half-open window. |
| `open_orders` | `market_id` | List the account's open orders. |
| `query_order` | `market_id`, `order_id` | Look up one order. |
| `trades_history` | `market_id`, `start`, `end` | Fetch the account's fills in a window. |
| `position` | `market_id`, `ttl`? | Fetch a margin market's position. |
| `available_notional` | `market_id`, `ttl`? | Fetch the notional the account can still open on a margin market. |
| `balances` | `market_id`, `ttl`? | Fetch a spot market's base and quote balances. |
| `collateral_id` | `market_id` | Fetch the collateral ID funding new orders on a margin market. |
| `place_order` | `market_id`, `order`, `settings`? | Place one order. `order` is `{"type", "qty", "price", "client_order_id"?}`, `type` one of `MARKET`, `LIMIT`, `POST_ONLY`, and a negative `qty` sells. |
| `cancel_order` | `market_id`, `order_id`, `settings`? | Cancel one order. |
| `cancel_open_orders` | `market_id`, `settings`? | Cancel every open order on the market. |
| `index` | `market_id`, `settings`? | Fetch the index price. |
| `next_funding` | `market_id`, `ttl`? | Fetch the upcoming funding rate. |
| `funding_rates` | `market_id`, `start`?, `end`? | Fetch historical funding rates. |
| `funding_payments` | `market_id`, `start`, `end` | Fetch the account's funding payments. |
| `perp_position` | `market_id`, `ttl`? | Fetch the perpetual position. |
| `collateral` | `market_id`, `ttl`? | Fetch the margin bucket backing a margin market. |
| `perp_collateral` | `market_id`, `ttl`? | Fetch the perpetual margin bucket backing the market. |
| `depth_stream` | `market_id`, `levels`?, `queue_size`?, `overflow`?, `settings`? | Subscribe to order books. |
| `trades_stream` | `market_id`, `queue_size`?, `overflow`?, `settings`? | Subscribe to the account's fills. |
| `unsub` | none | Stop the stream whose `id` this carries. |

`?` marks an optional field. `queue_size` and `overflow` (`"fail"` or `"latest"`) size
the gateway's buffer for the subscription.

`ttl` is how old an answer the caller accepts, as an ISO 8601 duration (`"PT1S"`). The
gateway keeps the answers it shares, so every task reading through one gateway shares
them: an answer whose request started less than `ttl` ago is reused, else a request in
flight is joined. Null or absent asks the venue afresh (ADR 0054).

## Replies and stream messages

| `tag` | Fields |
|---|---|
| `venues` | `venues`: list of account keys |
| `venue` | `venue_id` |
| `exchanges` | `exchanges`: list of `{"id", "type", "name", "url"?}` |
| `exchange` | `type` (`"spot"` or `"perp"`), `venue_id` |
| `markets` | `markets`: list of market IDs |
| `tickers` | `tickers`: object of market ID to `Ticker` |
| `perp_stats` | `stats`: object of market ID to `PerpStats` |
| `depth` | `book`: `Book` |
| `rules` | `rules`: `SpotRules` or `Rules` |
| `fees` | `fees`: `Fees` |
| `leverage`, `index`, `available_notional` | `value`: Decimal |
| `candles` | `candles`: list of `Candle` |
| `open_orders` | `orders`: list of `OrderState` |
| `query_order` | `order`: `OrderState` or `null` |
| `trades_history` | `trades`: list of `Trade` |
| `position` | `position`: `Position` |
| `balance` | `balance`: `Balance` |
| `balances` | `balances`: `SpotBalances` |
| `collateral_id` | `value`: collateral ID string |
| `perp_position` | `position`: `PerpPosition` |
| `place_order` | `response`: `OrderResponse` |
| `cancel_order`, `cancel_open_orders` | `result`: venue-specific JSON |
| `next_funding` | `rate`: `NextFunding` |
| `funding_rates` | `rates`: list of `FundingRate` |
| `funding_payments` | `payments`: list of `FundingPayment` |
| `collateral` | `collateral`: `PerpCollateral` or `Collateral` |
| `perp_collateral` | `collateral`: `PerpCollateral` |
| `depth_data` | `book`: `Book` |
| `trades_data` | `trade`: `Trade` |
| `err` | `error`: message, `exc`: exception class or `null` |
| `end` | `error`: message or `null`, `exc`: exception class or `null` |

`exc` names the SDK exception the gateway caught: `Error`, `NetworkError`,
`ValidationError`, `ApiError`, `BadRequest`, `AuthError`, `RateLimited`,
`OrderRejected`, `LogicError`, `ValueError` or `NotImplementedError`. Clients map any
other name to a generic error. An `end` without `error` is a clean end of the stream.

## Examples

A post-only order and its acknowledgement:

```json
{"tag":"place_order","id":"7c0e…","market_id":"dydx:perp:BTC-USD","order":{"type":"POST_ONLY","qty":"0.015","price":"64120.5","client_order_id":"42"},"settings":{"dydx":{"good_til_blocks":20}}}
{"tag":"place_order","id":"7c0e…","response":{"id":"dydx1…:0:42:0:1","details":{…},"filled_qty":null}}
```

A rejected order:

```json
{"tag":"err","id":"7c0e…","error":"could not immediately match","exc":"OrderRejected"}
```

A book update on a depth stream:

```json
{"tag":"depth_data","id":"9a41…","book":{"bids":[{"price":"99.5","qty":"2"}],"asks":[{"price":"100.5","qty":"3.25"}],"time":"2026-10-19T12:30:00.123456Z"}}
```

## Schema

[gateway-protocol.schema.json](https://github.com/tribulnation/sdk/blob/main/docs/gateway-protocol.schema.json) is JSON Schema 2020-12
generated from the codec: `$defs.ClientMsg` is any frame a client sends and
`$defs.ServerMsg` any frame the gateway sends. Both are unions discriminated by `tag`.
A test fails when the file is out of date. Regenerate it with:

```sh
python -c "import json; from tribulnation.sdk.gateway.codec import protocol_schema; print(json.dumps(protocol_schema(), indent=2))" > docs/gateway-protocol.schema.json
```

<!-- next -->

---

← [SDK gateway](gateway.md)

<!-- /next -->
