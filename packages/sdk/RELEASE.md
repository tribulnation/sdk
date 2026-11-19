# tribulnation-sdk 4.2.1

A patch release: faster `Book` hot paths, EVEDEX accounts and clarified depth `levels`.
Existing signatures are unchanged; adapters keep their current floors.

New:

1. `Evedex` accounts (`venue = "evedex"`) for `MarketSDK` and `ReportSDK`, served by
   tribulnation-evedex: an API key reads the account, the wallet's private key also
   trades, and `public` with neither serves market data only.

Changed:

1. `Book` keeps its levels in book order instead of re-deriving it
   ([ADR 0070](../../dev-docs/adr/0070-book-order-invariant-hot-paths.md)):
   `best_bid`/`best_ask` read the first level, `update` applies each delta by binary
   search, and `limit`, `copy` and `frozen` keep the order without re-sorting. Every
   book built from outside levels, including those decoded from the gateway wire, is
   still sorted on construction.
2. `Book.update` requires a book in book order. A changed or removed price replaces
   every level at that price; repeated prices the update does not touch are kept,
   where they were previously merged into the last one.
3. `Book.update` negates bid prices exactly (`copy_negate`), so a low-precision
   `Decimal` context no longer locates the wrong bid level.
4. The gateway's stream tasks read the shared frozen books without copying every
   level (the `reading_books_only` context variable); every other subscriber still
   gets its own copy (ADR 0049).
5. `depth`/`depth_stream` document `levels` as an upper bound: venues serve fewer
   levels when they publish fewer, and a value above a venue's maximum is served at that
   maximum, never refused. The adapter releases since 4.2.0 implement it.

The venue extras rise to the releases published since 4.2.0 (aster 0.16.1, binance
0.9.1, bit2me 0.10.2, bitget 0.14.2, bybit 0.10.3, coinbase 0.6.2, deribit 0.7.1, dydx
0.22.1, ethereum 0.6.2, extended 0.5.1, grvt 0.5.1, hyperliquid 0.22.2, kraken 0.9.2,
kucoin 0.7.1, lighter 0.15.1, margin-trade 0.4.1, mexc 3.0.2, nado 0.2.1, risex 0.2.1)
and add `evedex` (tribulnation-evedex 0.1.0, released after this version and qualified
public-only, [ADR 0072](../../dev-docs/adr/0072-public-only-release-qualification.md)).
