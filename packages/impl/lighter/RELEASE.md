# tribulnation-lighter 0.10.0

Requires SDK >=2.17.0 and typed-lighter >=0.2.0. Adds an immediate-or-cancel `LIMIT`
and a best bid/offer depth source.

New:

1. `place_order(..., settings={'lighter': {'time_in_force': 'immediate-or-cancel'}})`
   sends a `LIMIT` order immediate-or-cancel (no expiry). On `MARKET` or `POST_ONLY`
   it raises `ValueError` before signing. The submission is accepted even if nothing
   fills; the order then ends `canceled-*`, as before.
2. `depth_stream`/`depth` take `settings={'lighter': {'depth_source': ...}}`:
   `'order_book'` (default, unchanged: the full book from the snapshot and 50 ms
   deltas) or `'bbo'` (the `ticker` channel, best bid and ask on every book nonce).
   Each market and source shares one upstream; sources can run in parallel. Both use
   `last_updated_at` for `Book.time`, so they share one clock. REST `depth` trims to
   one level for `'bbo'`. An unknown source raises `ValueError`.

`OrderResponse.filled_qty` is `None`: the API acknowledges the transaction before
the sequencer matches it.

IOC orders are verified by unit fixtures only, not live (testnet included). The depth
sources had a 10-second public mainnet smoke check.

The SDK floor rises to 2.17.0, released with this adapter. Upgrade the SDK and this
adapter together.

Release qualification on 2026-10-09 passed the read suites and market
consistency. Committed evidence under `release-evidence/lighter/` matches pinned
Catalogue `1851660ac2bed8243dd9ce9c7297fe05c7130973`; offline release
verification passes. This adapter release follows SDK 2.17.0 publication.
