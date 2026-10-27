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

# Extended Market

> Perpetuals. `tribulnation-extended`, venue names `extended` and `extended_testnet`.

See the [generic market interface](../index.md) for the shared method surface. This page
covers only what is Extended-specific.

## Account

```toml
[accounts.extended]             # one sub-account: reads, cancels and orders
venue = "extended"              # or "extended_testnet"
api_key = "$EXTENDED_API_KEY"
stark_private_key = "$EXTENDED_STARK_PRIVATE_KEY"
vault = "$EXTENDED_VAULT"

[accounts.extended-read]        # the same sub-account, read-only
venue = "extended"
api_key = "$EXTENDED_API_KEY"
```

An API key belongs to one sub-account of a wallet, and every account read is that
sub-account's. The key alone reads and cancels; placing orders also needs the
sub-account's Stark private key and vault (and optionally `stark_public_key`, checked
against it), all shown on the venue's API management page. Another sub-account needs its
own account entry. With the fields omitted, `extended` reads `EXTENDED_API_KEY`,
`EXTENDED_STARK_PRIVATE_KEY`, `EXTENDED_STARK_PUBLIC_KEY` and `EXTENDED_VAULT`, and
`extended_testnet` the same names prefixed `EXTENDED_TESTNET_`. `public = true` serves
market data only.

## IDs

- One exchange, `perp`. Market ids are the venue's market names (`BTC-USD`), the same on
  mainnet and testnet. `markets()` lists the `ACTIVE`, `REDUCE_ONLY` and `PRELISTED`
  ones; `rules().api` is true for `ACTIVE` only.
- The collateral, fee and funding asset is `USD`. Order ids are Extended's numeric order
  ids.

## Semantics

- Most markets are RFQ markets, whose REST book is only indicative: `depth` reads the
  first snapshot of the RFQ quotes stream there, and `depth_stream` maintains the quotes.
  Other markets' `depth` is the whole aggregated REST book, with no timestamp.
- Tickers carry no best-level sizes. On RFQ markets their bid and ask are the venue's
  indicative book, so they need not match `depth`; request `depth()` for executable
  prices ([ADR 0048](https://github.com/tribulnation/sdk/blob/main/dev-docs/adr/0048-extended-rfq-indicative-tickers.md)).
- `rules().fees` is `None`: no standard schedule is published. `fees()` is the
  sub-account's maker and taker rate; RFQ markets charge the taker rate on every order.
- `place_order`: `LIMIT` rests good-till-time until the network's longest expiry (90
  days on mainnet, 28 on testnet, less a minute), `POST_ONLY` adds the post-only flag
  (RFQ markets refuse it, before signing), and `MARKET` is the venue's IOC market order
  bounded by `price`. RFQ markets' orders go through the RFQ endpoint. Off-grid prices
  and sizes raise `ValueError` before signing. `client_order_id` is the order's client
  id (`externalId`), 32 hex digits from `random_client_order_id()`. The venue does not
  keep client ids unique: reusing one places a second order.
- Acceptance is asynchronous: `OrderResponse.filled_qty` is `None`, and an order the
  matching engine refuses later shows as `REJECTED` in `query_order` (a crossing
  `POST_ONLY` ends `REJECTED` with `statusReason` `POST_ONLY_FAILED`). `OrderRejected` is
  raised only for a refusal the venue answers with an error code, such as `1140` (the
  order's cost exceeds the available balance) or `1120` (a size below the minimum),
  other than `1134` (the same signed order sent twice, so the first may rest) and `1006`
  (unhandled error).
- `open_orders` lists the market's open `LIMIT` orders, and `cancel_open_orders` cancels
  exactly those, in one mass cancel: conditional, TP/SL and TWAP orders placed elsewhere
  are neither listed nor cancelled. `cancel_order` takes any order id, a conditional
  order's included. Cancellation is asynchronous.
- Trade history reads the 10,000 most recent fills; the exchange-wide form leaves out
  spot fills and keeps delisted perpetuals.
- Collateral is the sub-account's one cross bucket, whatever the market, and every
  market's `collateral_id()` is that pool, `<account>:perp` (ADR 0051). The account is
  unified: spot holdings add to equity and spot buy orders reserve collateral too, but
  orders spend the pool's `availableForTrade`, not the `USD` spot balance, so the ID names
  the pool; a spot exchange added later must give its `USD` quote the same ID. The maintenance
  requirement is `marginRatio x equity`. `marginRatio` is a fraction rounded up to four
  decimals, so the figure can overstate the requirement by up to `0.0001 x equity`.
  `available_notional` is free collateral times the account's leverage, without the
  margin schedule's position-value cap.
- Funding settles hourly, on the hour, and the payment is stamped shortly after (45 s
  on testnet). Funding-rate history is positive when longs pay; `funding_payments`, per
  market or exchange-wide, are positive when received, as the venue signs them.
- Public and account reads are verified on mainnet, the account reads on an account
  without funds. Order placement and cancellation, fills and funding payments are
  verified on testnet only, where no RFQ quote was available to fill an RFQ order.
  Streams are verified on mainnet only: the testnet stream host refuses connections
  (`503`).

No `settings` are read.

<!-- next -->

---

← [Deribit Market](deribit.md) · **Next:** [GRVT Market](grvt.md) →

<!-- /next -->
