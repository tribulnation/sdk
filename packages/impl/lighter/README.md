# Lighter SDK

Perpetual and spot Market support for [Lighter](https://lighter.xyz/), built on
`typed-lighter`. Install with `pip install tribulnation-lighter`.

```python
from tribulnation.lighter import LighterMarket

async with LighterMarket.new(public=True) as venue:
  perp = await venue.perp_exchange('perp')
  market = await perp.market('1')  # BTC
  book = await market.depth(levels=5)
```

Account and trading methods need an API key registered for the account:

```python
venue = LighterMarket.new(account_index=476, api_key_index=4, api_private_key='0x…')
```

With no arguments, the client reads `LIGHTER_ACCOUNT_INDEX`, `LIGHTER_API_KEY_INDEX` and
`LIGHTER_API_PRIVATE_KEY` (`LIGHTER_TESTNET_*` with `network='testnet'`).

1. Exchanges are `perp` and `spot`. Market ids are the venue's numeric `market_id`
   (`'0'` ETH and `'1'` BTC perpetuals, `'2048'` ETH/USDC spot on mainnet): the ids orders
   are signed with. Symbols are API metadata only, and ids differ between networks.
   Asset ids are the venue's `asset_id` (`'3'` is USDC).
2. Public data: discovery, tickers, rules, REST depth (the top 250 orders per side,
   summed per price), a shared full-book stream, candles in the six SDK intervals,
   perpetual index, `perp_stats`, next funding and hourly funding-rate history.
3. Account and trading: fees (the account's fee ticks, in parts per million), order
   queries, open orders, trade history and streams with fees, positions, collateral,
   available notional, funding payments, `MARKET`, `LIMIT` and `POST_ONLY` orders, and
   every cancellation method. Order ids are client order indexes.
4. Perpetual fees, margin and funding are in USDC. Spot fees are charged in the asset a
   fill delivers, so spot `rules().fee_asset` is `None` and each `Trade.fee` names it.
5. Perpetual collateral covers cross and isolated positions. Spot collateral supports
   unified accounts only.

See [Lighter Market](../../../docs/market/implementations/lighter.md) for account
configuration through `MarketSDK` and venue-specific semantics.
