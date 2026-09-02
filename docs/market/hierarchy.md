# Hierarchy & Scoping

Every call ultimately runs against a `Market`. The other classes just narrow an ID one
segment at a time and delegate:

```
TradingMarkets   (MarketSDK)        keyed by your account IDs
  └─ TradingVenue                   one account on one venue
       └─ Exchange / PerpExchange   one market type (spot/perp) on that venue
            └─ Market / PerpMarket   one instrument
```

- `TradingMarkets` — the top-level collection you construct (`MarketSDK`). Maps your
  configured account IDs to venues.
- `TradingVenue` — a single configured account on a single venue. Exposes `exchange()`,
  `perp_exchange()`, `exchanges()`.
- `Exchange` / `PerpExchange` — a market *type* on a venue (e.g. dYdX `perp`, MEXC `spot`).
  Exposes `market()`, `markets()`. `PerpExchange` additionally yields `PerpMarket`s.
- `Market` / `PerpMarket` — a single instrument. This is where the real work happens; all
  the query/trade methods are defined here, and everything above forwards to them.

`Exchange`, `TradingVenue`, and `TradingMarkets` each re-expose the full `Market` method
surface (`depth`, `place_order`, …) with a leading `market_id` argument, so you can make
one-shot scoped calls without holding a `Market`. They are pure convenience wrappers: each
resolves the market and calls the identical method on it.

`collateral()` / `perp_collateral()` are special: they support **both** exchange-level (no
market) and market-level calls via optional `market_id`. See
[Collateral & account risk](collateral.md).

## Resolving IDs

- `TradingMarkets.venue(account_id)` → `TradingVenue`
- `TradingMarkets.exchange('<account_id>:<exchange_id>')` → `Exchange`
- `TradingMarkets.perp_exchange('<account_id>:<exchange_id>')` → `PerpExchange`
- `TradingMarkets.market('<account_id>:<exchange_id>:<market_id>')` → `Market`
- `TradingMarkets.perp_market(...)` / `TradingVenue.perp_market(...)` → `PerpMarket`
- `TradingMarkets.venues()` → the list of configured account IDs (built-ins included)
- `TradingVenue.exchanges()` → `[{'id': ..., 'type': 'spot' | 'perp'}, ...]`
- `Exchange.markets()` → list of available `market_id`s

Venues without perpetual support raise `NotImplementedError` from `perp_exchange()` (and
therefore from `perp_market`, `index`, `next_funding`, `funding_*`, `perp_position`).
