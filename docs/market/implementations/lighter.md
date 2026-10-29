<!-- github-only -->
<table><tr>
<td align="center"><a href="../../index.md">Docs</a></td>
<td align="center"><b>Market</b></td>
<td align="center"><a href="../../earn/index.md">Earn</a></td>
<td align="center"><a href="../../wallet/index.md">Wallet</a></td>
<td align="center"><a href="../../report/index.md">Report</a></td>
<td align="center"><a href="../../reference/index.md">Reference</a></td>
<td align="center"><a href="https://tribulnation.com/sdk/docs/support">Support matrix</a></td>
</tr></table>
<!-- /github-only -->

# Lighter Market

> Perpetuals and spot. `tribulnation-lighter`, venue names `lighter` and `lighter_testnet`.

See the [generic market interface](../index.md) for the shared method surface. This page
covers only what is Lighter-specific.

## Account

Three credential modes, by what the account configures:

| Method | Public | Read-only token | API key |
| --- | --- | --- | --- |
| Market data | yes | yes | yes |
| `position`, `collateral`, `perp_position`, `perp_collateral`, `leverage`, `available_notional`, `collateral_id`, `balances`, `collateral_ids`, `trades_history` | with `account_index` or `address` | yes | yes |
| `fees`, `open_orders`, `query_order`, `funding_payments`, `trades_stream` | no | yes | yes |
| `place_order`, `cancel_order`, `cancel_open_orders` | no | no | yes |

```toml
[accounts.lighter]           # API key: trading and every read
venue = "lighter"            # or "lighter_testnet"
account_index = "$LIGHTER_ACCOUNT_INDEX"
api_key_index = "$LIGHTER_API_KEY_INDEX"
api_private_key = "$LIGHTER_API_PRIVATE_KEY"

[accounts.lighter_readonly]  # read-only token, which names its account
venue = "lighter"
auth_token = "$LIGHTER_AUTH_TOKEN"

[accounts.lighter_public]    # public reads of the address's master account
venue = "lighter"
address = "$LIGHTER_ADDRESS"
public = true
```

Without credentials, account reads use `account_index` when configured, else the master
account (the venue's `account_type` 0) of `address`: sub-accounts need their own
`account_index`. Methods outside the account's mode raise `AuthError` naming what is
missing.

With the fields omitted, `lighter` reads `LIGHTER_ACCOUNT_INDEX`, `LIGHTER_API_KEY_INDEX`,
`LIGHTER_API_PRIVATE_KEY`, `LIGHTER_AUTH_TOKEN` and `LIGHTER_ADDRESS`, and
`lighter_testnet` the same names prefixed `LIGHTER_TESTNET_`. Testnet never falls back to
mainnet variables. A private account needs either the API key or the token; with the
API key variables set, the client signs even when the account configures only a token. `validate`
toggles response validation.

`rest_url` and `ws_url` (optional, `$ENV_VAR` allowed) override the REST API base URL
and the WebSocket stream URL, e.g. to run against a local test server. Unset, they follow
`venue`; the chain id always does.

## Exchange & ID conventions

- Exchanges are `perp` and `spot`. Market ids are the venue's numeric `market_id`, the
  id orders are signed with: `lighter:perp:1` (BTC), `lighter:spot:2048` (ETH/USDC).
  Symbols are API metadata only. Ids differ between mainnet and testnet.
- Asset ids are the venue's numeric `asset_id` (`3` is USDC).
- `Rules.fee_asset` is USDC on perpetuals and `None` on spot, whose fees are charged in
  the asset each fill delivers (the base asset on a buy, the quote asset on a sell).
  `Trade.fee` names it. Rules carry the standard account's rates, which are zero.

## Settings

`depth` and `depth_stream` accept `settings={'lighter': {'depth_source': ...}}`, typed
by the `Settings` TypedDict (`market/common.py`) alongside the order settings
`reduce_only` and `replaces`:

| Key | Type | Applies to | Meaning |
| --- | --- | --- | --- |
| `reduce_only` | `bool` | `place_order` | Place as reduce-only. |
| `replaces` | `str` | `place_order` | Modify this resting order to the order's price and size with one `L2ModifyOrder` instead of placing a new one. It keeps its id, side, time-in-force and reduce-only flag, so `MARKET`, `time_in_force` and `reduce_only` raise `ValueError` beside it. Unfilled orders only: Lighter doesn't document how a partly filled order's new size counts. A refusal is `BadRequest`, since the order still rests. |
| `depth_source` | `'order_book' \| 'bbo'` | `depth_stream`, `depth` | Which order-book channel to read; defaults to `'order_book'`. |

### Depth sources

| `depth_source` | Channel | Levels per side | Cadence |
| --- | --- | --- | --- |
| `'order_book'` (default) | `order_book/<market_id>` | full book | snapshot, then deltas every 50 ms |
| `'bbo'` | `ticker/<market_id>` | 1 (best bid/ask with sizes) | on every order book nonce |

```python
async with sdk.depth_stream('lighter:perp:1', settings={'lighter': {'depth_source': 'bbo'}}) as books:
  async for book in books:
    print(book.time, book.best_bid.price, book.best_ask.price)
```

- These are different channels and won't agree tick-for-tick: `'bbo'` pushes on
  every book nonce, while `'order_book'` batches its deltas every 50 ms.
- `Book.time` is the frame's `last_updated_at`, the time of the book change, on both
  sources, so books from either compare on one clock. The frame's send `timestamp` is
  not used. Both push only on change, so on a quiet book `time` stays put: old means
  unchanged, not necessarily stale.
- `'order_book'` verifies the delta chain (each frame's `begin_nonce` is the previous
  `nonce`) and fails the stream on a gap. `'bbo'` frames each carry the whole best
  bid/offer, so there is no chain to verify.
- On `'bbo'` a side with a zero price or size (an empty side) comes back as an empty
  `bids` or `asks`. `levels` only trims what the channel delivers and never selects
  it; an unknown `depth_source` raises `ValueError`.
- All consumers of one market and source share a single upstream subscription, so the
  sources of one market can be open side by side. Every channel is held on the
  client's one `/stream` connection, which Lighter caps at 500 subscriptions (and
  200 client messages per minute); each new market/source pair costs one
  subscription and one subscribe message.
- REST `depth` has no top-of-book endpoint: `'bbo'` reads the same resting-order
  snapshot, trimmed to 1 level per side, so its shape matches the stream's.

## Venue-specific semantics

- `fees()` reads the account's fee ticks, in parts per million, the same for buys and
  sells, perpetuals and spot. Testnet maker and taker fills on both kinds were charged
  exactly that tick, in the asset `Trade.fee` names. Trade fees are the tick of the account's role times the
  amount it pays on.
- REST depth sums the top 250 resting orders per side (about 200 levels on busy books);
  a side at the limit drops its possibly partial last level. Depth streams maintain the
  full book, shared per market, and fail on a sequence gap; `depth_source='bbo'`
  streams the best bid/offer instead (see [Depth sources](#depth-sources)).
- Tickers carry no best-level sizes.
- Tickers, perpetual stats and `next_funding` read the `market_stats` snapshot of a
  WebSocket subscription. The connection refuses a second subscription to an open channel,
  so concurrent readers of one snapshot always share one subscription, `ttl=None`
  included; `None` only skips a stored snapshot.
- `place_order` raises `OrderRejected` when the API refuses the transaction with a
  business code before the sequencer sees it. Code `21104` (invalid nonce), a code-less
  HTTP status and any `5XX` stay `BadRequest`/`ApiError`. An accepted transaction can
  still be refused by the sequencer later; that shows as a `canceled-*` order status,
  not as an error.
- `OrderResponse.filled_qty` is `None`: the API acknowledges the signed transaction
  before the sequencer matches it, so the response carries no execution.
- Candles support all six SDK intervals, walked in 500-candle windows.
- Orders: `LIMIT` rests good-till-time (28 days), `POST_ONLY` is rejected rather than
  taking liquidity, `MARKET` is the venue's market order bounded by `price`. Prices and
  sizes off the market's grid raise before signing. `settings={'lighter': {'reduce_only':
  True}}` places reduce-only orders, and `settings={'lighter': {'time_in_force':
  'immediate-or-cancel'}}` sends a `LIMIT` order immediate-or-cancel with no expiry
  (set on `MARKET` or `POST_ONLY`, it raises `ValueError`). An IOC that fills nothing is
  still accepted; it ends with a `canceled-*` status. `settings={'lighter': {'replaces':
  id}}` moves the resting order `id` to the order's price and size with one modify
  transaction instead of a cancel and a placement; the response keeps `id`.
- Creates, modifies and single-order cancels sent while another order transaction is in
  flight, or together in one event-loop turn, wait for it and go as one `sendTxBatch` of up
  to 15. A lone one goes alone, as before. A batch Lighter refuses raises `ApiError` for
  each of its transactions, never `OrderRejected`: the refusal names no transaction
  ([ADR 0057](https://github.com/tribulnation/sdk/blob/main/dev-docs/adr/0057-lighter-batched-order-transactions.md)).
- Order ids are client order indexes. `query_order` finds inactive orders for 24 hours,
  and misses a just-cancelled order for a few seconds while the venue indexes it.
- Spot `cancel_open_orders` cancels order by order: the venue's market-scoped cancel-all
  rejects spot markets.
- Trade times are the trade's block timestamp, a few seconds before execution.
- Perpetual collateral: the exchange bucket is cross margin; a market held in isolated
  margin reports its own bucket.
- Perpetual `leverage` is `1 / initial margin fraction`: the account's configured fraction
  for the market (the account's position entry, `initial_margin_fraction`, in percent), or
  the market's `default_initial_margin_fraction` for a market the account never
  configured. The fraction applies to cross and isolated positions alike. It is read
  from the same `/account` answer as positions and collateral, which reads with a `ttl`
  share. Perpetual `available_notional` is the free
  cross collateral times it, kept over the SDK default because isolated positions are
  funded from cross collateral rather than their own bucket.
- Spot `balances` support unified accounts only; classic accounts raise
  `NotImplementedError`. A margin-enabled asset (USDC) totals its `margin_balance`, shared
  with perpetuals, and frees `available_balance - locked_balance`; any other asset is its
  spot `balance`, less `locked_balance`. Spot rules and collateral IDs name assets by
  numeric id (`<account>:spot:3` is USDC).
- A perpetual's `collateral_id()` follows the account's trading mode, read once and
  cached: spot USDC (`<account>:spot:3`) on a unified account, whose perpetual margin is
  that balance, and `<account>:perp` on a classic one. Isolated positions return the same
  ID: they are funded from cross collateral (ADR 0051).
- Funding settles hourly. Funding-rate history is signed by the paying side (positive
  when longs pay); funding payments are positive when received.
- Public reads, including public account reads, are verified on mainnet. Token reads
  and trading methods are verified on testnet only.

<!-- next -->

---

← [GRVT Market](grvt.md) · **Next:** [margin.trade Market](margin-trade.md) →

<!-- /next -->
