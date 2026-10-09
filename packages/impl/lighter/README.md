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
`LIGHTER_API_PRIVATE_KEY` (`LIGHTER_TESTNET_*` with `network='testnet'`), else a
read-only `LIGHTER_AUTH_TOKEN`. A token (`auth_token='ro:…'`) allows every read but no
trading. Without credentials, `public=True` with an `account_index`, or an `address`
whose master account is used, still reads positions, collateral, leverage and trade
history; fees, orders and funding payments need a token or an API key.

1. Exchanges are `perp` and `spot`. Market ids are the venue's numeric `market_id`
   (`'0'` ETH and `'1'` BTC perpetuals, `'2048'` ETH/USDC spot on mainnet): the ids orders
   are signed with. Symbols are API metadata only, and ids differ between networks.
   Asset ids are the venue's `asset_id` (`'3'` is USDC).
2. Public data: discovery, tickers, rules, REST depth (the top 250 orders per side,
   summed per price), a shared full-book stream (or the `ticker` best bid/offer with
   `settings={'lighter': {'depth_source': 'bbo'}}`), candles in the six SDK intervals,
   perpetual index, `perp_stats`, next funding and hourly funding-rate history.
3. Account and trading: fees (the account's fee ticks, in parts per million), order
   queries, open orders, trade history and streams with fees, positions, collateral,
   available notional, funding payments, `MARKET`, `LIMIT` and `POST_ONLY` orders, and
   every cancellation method. Order ids are client order indexes.
4. Perpetual fees, margin and funding are in USDC. Spot fees are charged in the asset a
   fill delivers, so spot `rules().fee_asset` is `None` and each `Trade.fee` names it.
5. Perpetual collateral covers cross and isolated positions. Spot collateral supports
   unified accounts only, and raises `NotImplementedError` on classic accounts.

`Report` snapshots every account (master and sub-accounts) of an L1 address, with no
credentials:

```python
from tribulnation.lighter import Report

async with Report.new('0x…') as report:
  record = await report.snapshot()
```

Each account is a `<index>` subaccount with its spot and margin balances, isolated
margin, and positions. Pool shares (public pools, the LLP, LIT staking) are
`<index>:pool:<pool>` subaccounts holding the pro-rata part of the pool's balances; an
operated pool contributes only the operator's shares. `Report.new` also takes the index
of any account instead, and looks up its address. Through `ReportSDK`, the account's
`address` (default `LIGHTER_ADDRESS`) is used when set, else its `account_index`, so a
`MarketSDK` account configuration works unchanged. `history()` is not supported.

See [Lighter Market](../../../docs/market/implementations/lighter.md) for account
configuration through `MarketSDK` and venue-specific semantics.

## Funding payment signs

Since 0.4.0, funding payments are positive when received and negative when
paid, for every supported history scope. Requires SDK >=2.10.0. Funding rates keep
their existing signs. See [migration notes](RELEASE.md) before upgrading.
