# Aster SDK

Spot and linear perpetual Market support for [Aster](https://www.asterdex.com/),
built on `typed-aster`. Install with `pip install tribulnation-aster`.

```python
from tribulnation.aster import AsterMarket

async with AsterMarket.new(public=True) as venue:
  market = await venue.perp.market('BTCUSDT')
  book = await market.depth(levels=5)
```

Authenticated use needs the main wallet's address (`user`) and the private key of a
trading agent registered for it (`signer`). The main wallet's own key is never needed:

```python
venue = AsterMarket.new(user='0x…', signer='0x…', mainnet=False)
```

1. Exchanges are `spot` and `perp`, with native symbols such as `BTCUSDT`.
2. Public data: discovery, tickers, rules, REST depth (up to 1000 levels), shared
   depth streams (up to 20 levels), candles in the six SDK intervals, perpetual index,
   next funding and funding-rate history.
3. Account and trading: fees, order queries, open orders, fill streams, `MARKET`,
   `LIMIT` (GTC) and `POST_ONLY` (GTX) orders, and all cancellation methods. Market
   orders ignore the SDK `price`. Perpetual position and collateral cover one-way,
   cross-margin accounts. These are verified on testnet only.
4. Unsupported methods raise `NotImplementedError`: spot balances, trade history,
   funding payments, bulk `perp_stats`, `available_notional` and `perp_collateral`.
5. `tribulnation.aster.Report` streams perpetual income and spot transactions as
   unclassified cash deltas. It is verified on testnet only and not routed through
   `ReportSDK`.

See [Aster Market](../../../docs/market/implementations/aster.md) for account
configuration through `MarketSDK`.
