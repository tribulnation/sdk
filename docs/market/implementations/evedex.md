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

# EVEDEX Market

> Perpetuals. `tribulnation-evedex`, venue name `evedex`.

See the [generic market interface](../index.md) for the shared method surface. This page
covers only what is EVEDEX-specific.

## Account

```toml
[accounts.evedex]               # trading: the wallet's private key
venue = "evedex"
private_key = "$EVEDEX_PRIVATE_KEY"

[accounts.evedex-read]          # the same account, read-only
venue = "evedex"
api_key = "$EVEDEX_API_KEY"
```

An API key alone serves every account read. The wallet's private key signs in, signs
every order and opens the private fills stream; it reads the account too. With the
fields omitted, `evedex` reads `EVEDEX_API_KEY` and `EVEDEX_PRIVATE_KEY`, and
`typed-evedex` fills an unset key from the same variables when the other one is given.
`public = true` with neither key serves market data only. The venue is the production
exchange (evedex.com); the demo exchange (evedex.io) is not supported, since its trading
balance cannot be funded through the API.

## IDs

- One exchange, `perp`. Market ids are instrument names (`BTCUSD`, `1000PEPEUSD`).
  `markets()` lists the visible instruments; `rules().api` is false for those not open
  to every account (`marketMakerOnly`, a closed session or a stopped matcher).
- The collateral, fee and funding coin is `usdt`, as the venue writes it. Order ids are
  `DDDDD:<26 hex>` (days since 2025-07-24, then random hex), chosen by the client that
  places the order.

## Semantics

- `depth` and `depth_stream` serve the whole aggregated book, at most 100 levels a side,
  stamped with the venue's book time. Every stream publication is a full book, not a
  delta; markets share one connection.
- Tickers take the last price and 24h volumes (base and USD) from one instrument read,
  and the best bid and ask from one top-of-book request per market.
- `rules()` carries the tick, step, quantity bounds, the 5 USD minimum notional, the
  instrument's standard fee rates and relative price bounds from its mark-price band
  (`markPriceLimit`: ±30% of the mark on most instruments, ±50% on some). The absolute
  price range the venue accepts now is in `details`. `fees()` is the account's rates.
- Candles serve `1m`, `5m`, `15m`, `1h`, `4h` and `1d`, with volume in the base asset
  and in USD.
- `index` is the base coin's index price times the instrument's lot size (1000 on
  `1000PEPEUSD` and `1000BONKUSD`).
- EVEDEX computes funding every 8 hours and settles it hourly, an eighth of the rate each
  hour. `next_funding` and the funding in `perp_stats` are the next hourly settlement:
  the current rate divided by its 8-hour interval, at the next whole hour, positive when
  longs pay. `funding_rates` and `funding_payments` are not supported: the venue
  publishes no rate history, and its account ledger's funding entries name no market.
- Orders are limit orders, signed with the wallet, at the account's leverage on the
  market. That leverage comes from the last positions read, of any age: only the first
  order reads it, `set_leverage` and a refused order drop it, so a leverage changed by
  hand on the venue is read again after the next refusal. `LIMIT` rests until cancelled, and `MARKET` is an immediate-or-cancel limit at
  `price` (the venue's own market order is sized in USD and bounded only by its slippage
  limit); one that cannot fill ends cancelled. `POST_ONLY` is not supported: EVEDEX
  refuses post-only orders, so `place_order` and `replace_order` raise
  `NotImplementedError` before sending anything. Off-grid prices and sizes raise
  `ValueError` before signing. The venue executes orders asynchronously after accepting
  them, so `filled_qty` is `None`.
- `client_order_id` is sent as the order's own id, so it must have the venue's form;
  `random_client_order_id()` generates one. Fills report the order id as both
  `order_id` and `client_order_id`.
- A refused placement raises `OrderRejected`; cancelling an unknown id raises
  `OrderNotFound`. `replace_order` cancels, then places. `cancel_open_orders` is the
  venue's mass cancel of the market.
- `trades_history` reads each page's order sides in one request and the fills' fees
  with one request per order. `trades_stream` fills carry no fee, and their `id` is the
  venue's execution id while `trades_history` reports the fill's own id: the same fill
  has two different `Trade.id`s. Match a stream fill to its history row by `order_id`,
  price and time.
- Collateral is the account's one cross bucket, `<account>:perp` for every market:
  equity is the trading balance plus unrealized PnL, free collateral the venue's
  available balance. `perp_position` reports no liquidation price (the venue publishes a
  bankruptcy price only).
- `leverage()` is the market's setting, 1 where never set. `set_leverage` needs no
  signature and takes whole numbers up to the market's maximum.
- `remaining_position_limit` is the market's leverage-tier notional at the account's
  leverage, less the position held, at the mark. Accounts with their own leverage
  limits raise `NotImplementedError`.
- Market data, account reads, orders, cancels, leverage changes, fill history and the
  fills stream are verified on mainnet (2026-11-19, 6.6 XRP round trips).

<!-- next -->

---

← [Deribit Market](deribit.md) · **Next:** [Extended Market](extended.md) →

<!-- /next -->
