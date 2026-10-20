# Margin Trade SDK

Perpetual Market support for [Margin Trade](https://margin.trade), built on
`typed-margintrade`. Install with `pip install tribulnation-margintrade`.

```python
from tribulnation.margintrade import MarginTradeMarket

async with MarginTradeMarket.new('YourWalletAddress', public=True) as venue:
  perp = await venue.perp_exchange('perp')
  market = await perp.market('BTC')
  book = await market.depth(levels=5)
  position = await market.perp_position()
```

Margin Trade accounts are Solana wallets and every account read is public by address, so
no key is needed. Through `MarketSDK`, configure `accounts.MarginTrade(address=...)`; the
address defaults to `MARGINTRADE_ADDRESS` (`MARGINTRADE_TESTNET_ADDRESS` with
`venue='margintrade_testnet'`).

1. One exchange, `perp`. Market ids are the venue's coin names (`'BTC'`, `'NVDA'`,
   `'PRL'`); every market settles in USDC (asset id `'USDC'`).
2. Public data: discovery, rules, the aggregated `l2Book` and its stream, candles in the
   six SDK intervals, index (oracle) price, `perp_stats` and next funding.
3. Account reads: open orders, order lookup, fills, funding payments, positions, cross
   and isolated collateral, leverage and available notional.
4. Not supported: `tickers`, account `fees`, `trades_stream`, funding-rate history (empty upstream),
   and trading, which is not attempted until an account trades on the venue.

Fill history comes from the venue's newest 10,000 fills since `start`; when older fills
in the range were cut off, `trades_history` raises `ApiError` instead of returning a
partial history.
