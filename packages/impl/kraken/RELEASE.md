# tribulnation-kraken 0.9.1

Requires SDK >=4.1.0 and typed-kraken >=0.6.1, both unchanged.

Changed:

1. Perpetual `set_leverage` raises `NotImplementedError` before sending anything: Kraken cross leverage is the margin schedule's, and a leverage preference (`PUT /leveragepreferences`) would switch the market to isolated margin ([ADR 0066](../../../dev-docs/adr/0066-set-leverage-and-leverage-not-set.md)). It raised the SDK base's generic `NotImplementedError` before; the refusal now gives the reason, and `impl.toml` records it.
2. Order quantity and price, Spot and Futures, go through the SDK's `to_decimal` (behaviour change): a `float` input keeps its decimal digits (`0.1` is sent as `0.1`) instead of its binary expansion.

Every other method is unchanged.

Release qualification on 2026-11-19 passed the read suites and market consistency.
Committed evidence under `release-evidence/kraken/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes.

# tribulnation-kraken 0.9.0

Requires SDK >=4.1.0 (Kraken Futures keys on the account, [ADR 0065](../../../dev-docs/adr/0065-kraken-futures-and-spot-trading.md)) and typed-kraken >=0.6.1 (was >=0.4.0), for the authenticated Futures client; 0.6.1 accepts Futures history answers without a result marker.

Changed:

1. Futures perpetuals trade with a Futures API key (behaviour change; ADR 0065): orders (`LIMIT` `lmt`, `POST_ONLY` `post`, `MARKET` an IOC at the order price, `settings['kraken']` `time_in_force` and `reduce_only`), batch place/cancel, `replace_order` via `editorder`, and the private reads (open orders, query, position, the flex collateral pool, leverage, fees, trades and funding history). Without Futures keys perpetuals are public only.
2. Spot pairs are `SpotMarket`s traded with the Spot API key: `SpotRules`, `balances()`, `<account>:spot:<asset>` collateral IDs, and `AddOrder`/`AmendOrder` limits.
3. Perpetual `leverage()` falls back to the retail margin levels when the platform has no schedule for the market.

Every other method is unchanged.

Release qualification on 2026-11-18 passed the read suites and market consistency.
Committed evidence under `release-evidence/kraken/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows SDK 4.1.0 publication.
