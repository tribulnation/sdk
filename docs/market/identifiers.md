# Market Identifiers

IDs are colon-delimited and parsed left-to-right, one segment per scoping layer:

| Called on | ID shape |
| --- | --- |
| `TradingMarkets` (`MarketSDK`) | `<account_id>:<exchange_id>:<market_id>` |
| `TradingVenue` | `<exchange_id>:<market_id>` |
| `Exchange` / `PerpExchange` | `<market_id>` |

- **`account_id`** is the *key you registered in `accounts`* — not the venue's own name.
  Register `accounts.Dydx()` under `'dydx-1'` and the account ID is `dydx-1`. This lets you
  run several accounts on one venue side by side. The three built-in public accounts
  (`dydx`, `hyperliquid`, `mexc`) are always present unless you override those keys.
- **`exchange_id`** selects the market type on the venue: `perp` on dYdX, `spot` on MEXC,
  `spot` or a perp DEX name (empty string = the default perp DEX) on Hyperliquid.
- **`market_id`** is the venue-native instrument identifier and may itself contain colons
  (dYdX subaccount suffix, Hyperliquid spot index). Only the first two colons are
  significant to `TradingMarkets`; the rest is handed to the exchange verbatim
  (`id.split(':', 2)`).

Examples: `mexc_account1:spot:BTCUSDT`, `dydx:perp:BTC-USD`, `hyperliquid:spot:BTC/USDC:0`.

Equivalent ways to reach the same market:

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

Note: a `Market` object's own `id` property is `f'{venue_id}:{exchange_id}:{market_id}'` and
uses the *venue's* canonical name (e.g. `dydx`), not the account key you looked it up by.
