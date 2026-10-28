# Extended SDK

Perpetual Market and Report support for [Extended](https://extended.exchange/), built on
`typed-extended`. Install with `pip install tribulnation-extended`.

```python
from tribulnation.extended import ExtendedMarket

async with ExtendedMarket.new(public=True) as venue:
  perp = await venue.perp_exchange('perp')
  market = await perp.market('BTC-USD')
  book = await market.depth(levels=5)
```

An account is one sub-account of a wallet. Its API key reads it and cancels its orders;
placing orders also needs the sub-account's Stark private key and vault:

```python
venue = ExtendedMarket.new(api_key='…', stark_private_key='0x…', vault=12345)
```

With no arguments, the client reads `EXTENDED_API_KEY`, `EXTENDED_STARK_PRIVATE_KEY`,
`EXTENDED_STARK_PUBLIC_KEY` and `EXTENDED_VAULT` (`EXTENDED_TESTNET_*` with
`network='testnet'`). A wallet's other sub-accounts each need their own API key.

1. One exchange, `perp`. Market ids are the venue's market names (`BTC-USD`), the same on
   both networks; the collateral, fee and funding asset is `USD`.
2. Public data: discovery, tickers, rules, depth, a shared book stream, candles in the
   six SDK intervals, index, `perp_stats`, next funding and hourly funding-rate history.
   RFQ markets' books are their quotes, from the RFQ quotes stream.
3. Account and trading: fees, order queries, open orders, trade history and the fills
   stream, positions, collateral, leverage, available notional, `MARKET`, `LIMIT` (or
   immediate-or-cancel with `settings={'extended': {'time_in_force': 'IOC'}}`) and
   `POST_ONLY` orders (RFQ markets through the RFQ endpoint), and every cancellation
   method. Order ids are Extended's numeric order ids; `client_order_id` is the order's
   `externalId`.
4. Acceptance is asynchronous: an order the matching engine refuses after acceptance
   shows as `REJECTED` in `query_order`; `OrderRejected` is raised for refusals the venue
   answers with an error code.
5. `funding_payments` raises `NotImplementedError` until the sign of the venue's payment
   amount is observed.

`Report` snapshots and streams the history of the API key's sub-account; a read-only key
is enough:

```python
from tribulnation.extended import Report

async with Report.new('…') as report:
  record = await report.snapshot()
```

History yields asset operations (transfers between sub-accounts, deposits, withdrawals,
testnet claims), fills and closed positions with their realized PnL. It raises
`NotImplementedError` for a window holding a funding or borrow-interest payment.

See [Extended Market](../../../docs/market/implementations/extended.md) for account
configuration through `MarketSDK` and venue-specific semantics.
