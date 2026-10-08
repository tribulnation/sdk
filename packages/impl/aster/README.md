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
   next funding, funding-rate history and bulk `perp_stats` (open interest for at most
   five named contracts).
3. Account reads, verified on mainnet: fees, spot balances (mainnet only), spot and
   perpetual trade history (spot also exchange-wide), one-way perpetual position,
   cross or isolated `perp_collateral`, `leverage` and capped `available_notional`.
   Perpetual funding payments are available per market or exchange-wide, positive when
   received.
4. Trading, verified on testnet only: order queries, open orders, fill streams,
   `MARKET`, `LIMIT` (GTC) and `POST_ONLY` (GTX) orders, and all cancellation methods.
   Market orders ignore the SDK `price`.
5. Unsupported methods raise `NotImplementedError`: hedge-mode positions, exchange-wide
   perpetual trade history, order settings, and spot balances and trade history on
   testnet.
6. `tribulnation.aster.Report` snapshots, through `ReportSDK`, the mainnet `perp` wallet
   (without unrealized PnL) and positions with their entry prices, the `spot` wallet,
   and ASTER staked on Aster Chain with its unclaimed rewards, signed by the trading
   agent. Testnet snapshots are unsupported. Its
   `history()` streams perpetual income and spot transactions as unclassified cash
   deltas, verified on testnet only.

See [Aster Market](../../../docs/market/implementations/aster.md) for account
configuration through `MarketSDK`.

## Funding payment signs

Since 0.5.0, funding payments are positive when received and negative when
paid, for every supported history scope. Requires SDK >=2.10.0. Funding rates keep
their existing signs. See [migration notes](RELEASE.md) before upgrading.
