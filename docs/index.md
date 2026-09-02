# Tribulnation SDK

> One interface, every venue. Async, fully typed, decimal-precision Python for crypto trading and data.

## Why the SDK?

- **🎯 Swap venues by changing a string**: `Market`, `Wallet`, `Earn` and `Report` are abstract interfaces, so code written against them runs unchanged on every implemented venue, and on several accounts per venue side by side.
- **🛡️ Validated at the edge**: every implementation sits on our [Typed](/typed) clients, so venue responses are typed and validated before they reach you.
- **🔢 No raw primitives**: prices, sizes and fees are `Decimal`, timestamps are `datetime`, never `float` or epoch ints.
- **📊 Beyond trading**: `Report` reads balance and position history from exchanges *and* chains, `Earn` covers yield instruments, `Wallet` covers deposits and withdrawals.

## Installation

```bash
pip install tribulnation-sdk[dydx,hyperliquid,mexc]
```

Extras select which venue packages get installed. See the [support matrix](https://tribulnation.com/sdk/docs/support) for what's actually implemented per venue.

## Quick Start

**1. Define accounts** in `sdk.toml`:

```toml
[accounts.mexc_account1]
venue = "mexc"
api_key = "$MEXC_API_KEY"
api_secret = "$MEXC_API_SECRET"
```

`$VAR` values resolve from the environment, and a missing one fails at load time rather than on first use. Public venues (`dydx`, `hyperliquid`, `mexc`) work without an entry.

**2. Trade**:

```python
from tribulnation.sdk import MarketSDK

sdk = MarketSDK.load('sdk.toml')
async with sdk.trades_stream('mexc_account1:spot:BTCUSDT') as my_trades:
  async for my_trade in my_trades:
    print(f'Hedging {my_trade}')
    await sdk.place_order('dydx:perp:BTC-USD', {
      'type': 'LIMIT', 'qty': -my_trade.qty, 'price': my_trade.price
    })
```

Or construct in code: `MarketSDK({'mexc_account1': accounts.Mexc()})`. Each `accounts.<Venue>()` field defaults to `$VENUE_FIELD`, e.g. `accounts.Mexc()` reads `$MEXC_API_KEY` and `$MEXC_API_SECRET`.

## Market IDs & Scoping

`<account_id>:<exchange_id>:<market_id>`, e.g. `mexc_account1:spot:BTCUSDT`. `account_id` is the key you registered in `accounts` (not necessarily the venue's own name), so you can run several accounts on one venue side by side. Equivalent ways to reach a market:

```python
await sdk.depth('mexc_account1:spot:BTCUSDT')

venue = await sdk.venue('mexc_account1')
await venue.depth('spot:BTCUSDT')

exchange = await venue.exchange('spot')
await exchange.depth('BTCUSDT')

market = await exchange.market('BTCUSDT')
await market.depth()
```

Hold a `Market` reference in hot loops; use the scoped one-shot calls otherwise.

## Error Handling

All errors subclass `Error`: `NetworkError`, `ValidationError`, `ApiError` (`BadRequest`, `AuthError`, `RateLimited`), `LogicError`.

## Reference

- [Lifecycle](lifecycle.md) — every SDK object is an async context manager
- [Context, Logging & Retries](context.md) — opt-in logging and retries
- [Market](market/index.md) — order books, rules, orders, positions, funding; see also [Market Identifiers](market/identifiers.md) and [Collateral & Risk Management](market/collateral.md)
- [Earn](earn/index.md) — yield-bearing instruments across venues
- [Wallet](wallet/index.md) — deposit/withdrawal methods
- [Report](report/index.md) — balance/position history, with provenance

## Support Matrix

Not every venue implements every surface yet. See the [support matrix](https://tribulnation.com/sdk/docs/support) for what's actually wired, per venue and per surface.
