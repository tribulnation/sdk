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

# RISEx Market

> Perpetuals. `tribulnation-risex`, venue names `risex` and `risex_testnet`.

See the [generic market interface](../index.md) for the shared method surface. This page
covers only what is RISEx-specific.

## Account

```toml
[accounts.risex]                # trading: a registered signer key
venue = "risex"                 # or "risex_testnet"
address = "$RISEX_ADDRESS"
signer_key = "$RISEX_SIGNER_KEY"

[accounts.risex-read]           # the same account, read-only
venue = "risex"
address = "$RISEX_ADDRESS"
public = true
```

RISEx has no API keys. Every account read is public, keyed by the account's address, so
an `address` alone serves them. A registered signer (session) key signs orders and
cancels and authenticates the fills stream; either it or the account wallet's own
`account_key` (whose address then defaults the `address`) logs in for `fees()`. The
account key never trades. With the fields omitted, `risex` reads `RISEX_ADDRESS`,
`RISEX_ACCOUNT_KEY` and `RISEX_SIGNER_KEY`, and `risex_testnet` the same names prefixed
`RISEX_TESTNET_`. `public = true` with no address serves market data only. Mainnet
trading is invite-only.

## IDs

- One exchange, `perp`. Market ids are the venue's numeric `market_id` as a decimal
  string (`'1'` is BTC/USDC on mainnet and testnet). Market names are not unique, so
  they are not ids. `markets()` lists the `active` and unlocked markets; `rules().api`
  also excludes reduce-only ones.
- The collateral, fee and funding asset is `USDC`. Order ids are the venue's composite
  ids (`0x` and 48 hex digits).

## Semantics

- `depth` is the aggregated REST book, at most 250 levels a side, with no timestamp.
  `depth_stream` maintains the book from the venue's snapshot and per-block level
  updates, stamped with each frame's time; each market's stream has its own connection.
- Tickers carry only the last price and the 24h quote volume: the venue publishes no
  best bid/ask in its market data, nor a base volume. `perp_stats` open interest is in
  base units.
- `rules().fees` is `None`: the fee schedule is served to logged-in accounts only.
  `fees()` is the account's tier rates, one maker and one taker rate for every market;
  a negative maker rate is a rebate.
- Candles serve `1m`, `5m`, `15m`, `1h`, `4h` and `1d`, as the venue sends them: some
  have an `open` or `close` outside their `low`..`high` range.
- `place_order` signs an EIP-712 permit; sizes and prices are sent in whole steps and
  ticks, so off-grid values raise `ValueError` before signing. `LIMIT` rests until
  cancelled, `POST_ONLY` adds the post-only flag, and `MARKET` is an immediate-or-cancel
  limit at `price` (the venue's own market order does not bound its fill by its price).
  Placements and cancels are on-chain transactions the venue waits for, so a placement's
  reply is final: `filled_qty` is reported for `MARKET` orders, `None` for resting ones.
  `client_order_id` is a decimal integer (`random_client_order_id()` draws one below
  2^63).
- A refused placement raises `OrderRejected`, nothing resting: a crossing `POST_ONLY`
  (`PostOnlyOrderMatched()`), a size below the minimum (`BelowMinOrderSize`), a price
  too far from the mark (`OrderPriceOutsideMatchBand`). Cancelling an order that no
  longer rests raises `OrderNotFound`. `replace_order` cancels, then places: RISEx has
  no modify. `cancel_open_orders` cancels every resting order of the market in one
  transaction.
- Collateral is the account's one cross bucket, whatever the market, and every market's
  `collateral_id()` is that pool, `<account>:perp`. Equity is the USDC balance plus the
  cross positions' unrealized PnL. Accounts holding an isolated position raise
  `NotImplementedError` from it.
- `leverage()` is the market's leverage setting, the market's maximum where it was never
  set.
- Funding settles hourly. `next_funding` and the funding in `perp_stats` are the venue's
  estimate of the next rate, positive when longs pay. `funding_payments` are positive
  when received, unsettled accruals of an open position included; on an account with an
  open position they currently fail validation (`typed-risex` 0.1.0).
- Market data and account reads are verified on mainnet; orders, cancels, fills and the
  fills stream on testnet only.

<!-- next -->

---

← [Nado Market](nado.md) · **Next:** [Earn](../../earn/index.md) →

<!-- /next -->
