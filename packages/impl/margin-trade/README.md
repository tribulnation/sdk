# margin.trade SDK

Spot and USDC-margined perpetual Market support, and Report snapshots and history, for
[margin.trade](https://margin.trade/), built on `typed-margin-trade`. Install with
`pip install tribulnation-margin-trade`.

```python
from tribulnation.margin_trade import MarginTradeMarket

async with MarginTradeMarket.new() as venue:
  market = await venue.perp.market('BTC')
  book = await market.depth(levels=5)
```

Accounts are Solana Ed25519 keys; the account is the master key's base58 address. Trading
needs the master's key or an approved agent's (API wallet), with `address` set to the
master. Account reads are by address and need no key:

```python
venue = MarginTradeMarket.new(address='6dm8…', private_key='<agent key>', mainnet=False)
reads = MarginTradeMarket.new(address='6dm8…')
```

1. Exchanges are `perp` (coin names such as `BTC`, `XAU`, `NVDA`) and `spot` (pair names
   such as `PEARL/USDC`). Asset ids are token symbols (`USDC`, `PEARL`); perpetual fees are
   charged in `USD`.
2. Public data: discovery, tickers (24h volumes, plus last and best bid/ask where the
   venue's CoinGecko feed lists the market), rules with each market's own fee rates,
   REST depth and shared `l2Book` depth streams, candles in the six SDK intervals,
   perpetual index (oracle price), next funding (hourly) and `perp_stats`. No
   funding-rate history: the venue serves placeholder data.
3. Account and trading: order queries, open orders, trade history (per market or
   exchange-wide) and per-coin fill streams, positions, cross collateral, leverage,
   available notional, perpetual funding payments, and `MARKET` (an `Ioc` limit),
   `LIMIT` (`Gtc`) and `POST_ONLY` (`Alo`) orders with every cancellation method. Order
   placement is verified on testnet only. `fees` is unsupported: the venue's account
   rate is not what fills are charged.
4. Report: a `perp` subaccount (USDC without unrealized PnL, positions) and a `spot`
   subaccount (token totals); history of fills, funding and transfers (on-chain deposits
   and withdrawals on `solana` or `pearl`, perp/spot transfers).
5. Streams need `typed-margin-trade` 0.1.1 or later, which pings every 10 s: the venue
   drops a connection about 30 s after the client's last ping.
