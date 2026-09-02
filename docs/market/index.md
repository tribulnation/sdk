# Market

> `Market` places orders and queries data for a single account/exchange/market. The
> surrounding objects (`Exchange`, `TradingVenue`, `TradingMarkets`) are thin scoping
> layers that resolve an ID down to a `Market` and forward the call.

- [Methods](methods.md) — the full method reference, with a per-venue example for each
- [Market Identifiers](identifiers.md) — the `account:exchange:market` grammar
- [Hierarchy & Scoping](hierarchy.md) — how IDs resolve to venue, exchange and market objects
- [Collateral & Risk Management](collateral.md) — the margin-bucket model behind `collateral()`
- [Streaming](streaming.md) — order-book and trade streams, and their overflow policies
- [Implementations](implementations/index.md) — what each venue does differently

## Example

```python
from dotenv import load_dotenv
from tribulnation.sdk import MarketSDK, accounts

load_dotenv()  # load credentials from .env

sdk = MarketSDK(
  {
    'mexc_account1': accounts.Mexc(
      api_key='$MEXC_API_KEY', api_secret='$MEXC_API_SECRET'
    ),
    # 'dydx', 'hyperliquid', and 'mexc' are available by default even without listing them
  }
)

mexc = await sdk.market('mexc_account1:spot:BTCUSDT')
dydx = await sdk.market('dydx:perp:BTC-USD')

async with mexc.trades_stream() as my_trades:
  async for my_trade in my_trades:
    print(f'Hedging {my_trade}')
    await dydx.place_order(
      {
        'type': 'LIMIT',
        'qty': -my_trade.qty,
        'price': my_trade.price,
      }
    )
```

## Context, logging & retries

Every method above is wrapped with `@SDK.method`, so it participates in the active
`Context` (opt-in logging/retries). Because the scoping layers call through to the
`Market`, a persistent failure can be retried at each layer it passes through. See
[Context, Logging & Retries](../context.md).
