# GRVT SDK

USDT-margined perpetual and spot Market support, and Report snapshots, for
[GRVT](https://grvt.io/), built on `typed-grvt`. Install with
`pip install tribulnation-grvt`.

```python
from tribulnation.grvt import GrvtMarket

async with GrvtMarket.new() as venue:
  perp = await venue.perp_exchange('perp')
  market = await perp.market('BTC_USDT_Perp')
  book = await market.depth(levels=5)
```

Credentials are passed explicitly; the environment is never read. An API key serves
every account read (a read-only key suffices); its EIP-712 signer key is needed only to
place orders. Without an API key the venue is public: market data only.

```python
reads = GrvtMarket.new(api_key='…')
trading = GrvtMarket.new(api_key='…', private_key='0x…', env='testnet')
```

1. Two exchanges, `perp` and `spot`. Market ids are instrument names (`BTC_USDT_Perp`,
   `GRVT_USDT_SpotSwap`), the same on mainnet and testnet; asset ids are currency codes
   (`USDT`). Spot instruments (GRVT's `SPOT_SWAP`) are order books settled in the
   trading sub-account's spot wallet; their collateral IDs are `<account>:spot:<asset>`.
2. Public data: discovery, tickers and `perp_stats` (one `ticker` request per market,
   sent concurrently), rules (perpetuals with GRVT's published tier-1 rates; spot
   publishes none), REST depth and a shared
   delta depth stream, candles in the six SDK intervals, index, next funding and
   funding-rate history (4- or 8-hour settlements).
3. Account and trading, on the trading sub-account (`trading_account_id`, else the one
   the API key is scoped to): the account's fee tier, order queries, open orders, trade
   history (per market or exchange-wide) and fill streams, positions, the cross and
   isolated collateral buckets, leverage, available notional, funding payments, the
   spot wallet's balances, and `MARKET`, `LIMIT` and `POST_ONLY` orders with every
   cancellation method. Order ids are client order ids. Perpetual trading is verified
   on testnet only; spot order placement is unverified.
4. Margin types and leverage are read, not set: set them on the venue.

`Report` snapshots the funding wallet and every trading sub-account the API key can
read:

```python
from tribulnation.grvt import Report

async with Report.new(api_key='…') as report:
  record = await report.snapshot()
```

Subaccounts are `funding`, `<sub_account_id>:futures` (cash balances, isolated
positions' balances included, without unrealized PnL, and positions by instrument name) and `<sub_account_id>:spot`. Vault investments,
borrowed balances and vault sub-accounts raise `NotImplementedError`. `history()` is not
supported.

See [GRVT Market](../../../docs/market/implementations/grvt.md) for account
configuration through `MarketSDK` and venue-specific semantics.
