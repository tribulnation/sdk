<p align="center">
  <a href="https://tribulnation.com/sdk/docs/market/implementations/risex">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://tribulnation.com/media/lockups/risex-dark.svg">
      <source media="(prefers-color-scheme: light)" srcset="https://tribulnation.com/media/lockups/risex-light.svg">
      <img alt="Tribulnation SDK RISEx" src="https://tribulnation.com/media/lockups/risex-light.svg" width="520">
    </picture>
  </a>
</p>

<p align="center">
  <em>Tribulnation SDK implementation for RISEx perpetuals.</em>
</p>

Perpetual Market and Report support for [RISEx](https://rise.trade/), built on
`typed-risex`. Install with `pip install tribulnation-risex`.

```python
from tribulnation.risex import RisexMarket

async with RisexMarket.new() as venue:
  perp = await venue.perp_exchange('perp')
  market = await perp.market('1')  # BTC/USDC
  book = await market.depth(levels=5)
```

RISEx has no API keys. Every account read is public, keyed by the account's address; a
registered signer (session) key signs orders and cancels:

```python
venue = RisexMarket.new(address='0x…')  # account reads only
venue = RisexMarket.new(address='0x…', signer_key='0x…', network='testnet')  # trading
```

The environment is never read here; `MarketSDK` resolves `RISEX_ADDRESS`,
`RISEX_ACCOUNT_KEY` and `RISEX_SIGNER_KEY` (`RISEX_TESTNET_*` for `risex_testnet`).

1. One exchange, `perp`. Market ids are the venue's numeric `market_id` (`'1'` is
   BTC/USDC on both networks); the collateral, fee and funding asset is `USDC`.
2. Public data: discovery, tickers (last price and quote volume), rules, depth, a shared
   book stream, candles in the six SDK intervals, index, `perp_stats`, the funding
   estimate and hourly funding-rate history.
3. Account and trading: order queries, open orders, trade history, positions,
   collateral, leverage and available notional by address; `fees` with a key; the fills
   stream, `MARKET` (an IOC limit), `LIMIT` and `POST_ONLY` orders and every
   cancellation method with the signer key. Placements are mined before the venue
   replies; refusals raise `OrderRejected`.
4. Isolated positions raise `NotImplementedError` from collateral reads and snapshots.

`Report` snapshots one account by address:

```python
from tribulnation.risex import Report

async with Report.new(address='0x…') as report:
  record = await report.snapshot()
```

See [RISEx Market](../../../docs/market/implementations/risex.md) for account
configuration through `MarketSDK` and venue-specific semantics.
