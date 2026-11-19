# EVEDEX SDK

Perpetual Market and Report support for [EVEDEX](https://evedex.com/), built on
`typed-evedex`. Install with `pip install tribulnation-evedex`.

```python
from tribulnation.evedex import EvedexMarket

async with EvedexMarket.new() as venue:
  perp = await venue.perp_exchange('perp')
  market = await perp.market('BTCUSD')
  book = await market.depth(levels=5)
```

An API key reads the account; the wallet's private key also signs orders and opens the
private fills stream:

```python
venue = EvedexMarket.new(api_key='…')  # account reads only
venue = EvedexMarket.new(private_key='0x…')  # reads and trading
```

`MarketSDK` resolves `EVEDEX_API_KEY` and `EVEDEX_PRIVATE_KEY`; `typed-evedex` also
fills an unset key from them when the other one is given.

1. One exchange, `perp`, on the production exchange (evedex.com). Market ids are
   instrument names (`BTCUSD`); the collateral, fee and funding coin is `usdt`.
2. Public data: discovery, tickers (best bid and ask, last price, 24h volumes), rules,
   depth, a shared book stream, candles in the six SDK intervals, index, `perp_stats`
   and the next hourly funding settlement. No funding-rate history is published.
3. Account and trading: fees, order queries, open orders, trade history, positions,
   collateral, leverage, available notional and remaining position limit with an API
   key; `set_leverage` too. The fills stream, `MARKET` (an IOC limit) and `LIMIT`
   orders and every cancellation method with the private key. EVEDEX refuses post-only
   orders, so `POST_ONLY` raises `NotImplementedError`. Stream fills carry no fee, and
   their ids differ from `trades_history`'s. Refusals
   raise `OrderRejected`. Funding payments are not supported.

`Report` snapshots one account, its trading balance and positions and its wallet:

```python
from tribulnation.evedex import Report

async with Report.new(api_key='…') as report:
  record = await report.snapshot()
```

See [EVEDEX Market](../../../docs/market/implementations/evedex.md) for account
configuration through `MarketSDK` and venue-specific semantics.
