<p align="center">
  <a href="https://tribulnation.com/sdk/docs/market/implementations/nado">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://tribulnation.com/media/lockups/nado-dark.svg">
      <source media="(prefers-color-scheme: light)" srcset="https://tribulnation.com/media/lockups/nado-light.svg">
      <img alt="Tribulnation SDK Nado" src="https://tribulnation.com/media/lockups/nado-light.svg" width="520">
    </picture>
  </a>
</p>

<p align="center">
  <em>Tribulnation SDK implementation for Nado spot and perpetual markets.</em>
</p>

USDT0-settled perpetual and spot Market support, and Report snapshots, for
[Nado](https://www.nado.xyz/), built on `typed-nado`. Install with
`pip install tribulnation-nado`.

```python
from tribulnation.nado import NadoMarket

async with NadoMarket.new() as venue:
  perp = await venue.perp_exchange('perp')
  market = await perp.market('BTC-PERP')
  book = await market.depth(levels=5)
```

Credentials are passed explicitly; the environment is never read. Nado has no API keys:
an `address` serves every account read, since Nado's reads are public, and the
`private_key` (the subaccount owner's, or its linked signer's) also places and cancels
orders. Without either the venue is public: market data only.

```python
reads = NadoMarket.new(address='0x…')
trading = NadoMarket.new(private_key='0x…', network='testnet')
```

1. Two exchanges, `perp` and `spot`. Market ids are product symbols (`BTC-PERP`,
   `KBTC`); asset ids are spot symbols and `USDT0`, the quote of every market.
2. Public data: discovery, tickers and `perp_stats` (bulk requests), rules with the
   products' default rates, REST depth and a shared diff depth stream (100 levels per
   side), candles in the six SDK intervals, index, next funding and hourly funding-rate
   history.
3. Account and trading, on one subaccount (`default` unless `subaccount` names another),
   a unified cross-margin account: per-product fee rates, order queries, open orders,
   trade history (per market or exchange-wide) and fill streams, positions, the cross
   bucket, leverage from the risk weights, available notional, funding payments, spot
   balances, and `MARKET` (immediate-or-cancel), `LIMIT` and `POST_ONLY` orders with
   every cancellation method and an atomic `replace_order`. Order ids are digests.
4. Isolated positions are not supported: account reads of a market holding one raise
   `NotImplementedError`.

`Report` snapshots every cross subaccount of a wallet:

```python
from tribulnation.nado import Report

async with Report.new(address='0x…') as report:
  record = await report.snapshot()
```

See [Nado Market](../../../docs/market/implementations/nado.md) for account
configuration through `MarketSDK` and venue-specific semantics.
