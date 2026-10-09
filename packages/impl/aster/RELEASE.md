# tribulnation-aster 0.11.0

Requires SDK >=2.17.0 and typed-aster >=0.4.0. Aster gains its own settings key
(`settings['aster']`), with an immediate-or-cancel `LIMIT` and selectable depth
sources, and perpetual placements report `OrderResponse.filled_qty`.

New:

1. `place_order(..., settings={'aster': {'time_in_force': 'IOC'}})` sends a `LIMIT`
   order `timeInForce: IOC` on spot and perpetuals. On `MARKET` or `POST_ONLY` it
   raises `ValueError` before anything is sent. An IOC that expires with nothing
   filled raises `OrderRejected`, like a crossing GTX; a partial fill is a normal
   response.
2. `depth_stream`/`depth` take `settings={'aster': {'depth_source': ...}}`:
   `'depth'` (default, unchanged: `@depth20`, 20 levels), `'fast'` (`@depth5@100ms`,
   5 levels) or `'bbo'` (`@bookTicker`, best bid and ask on every change). Each
   symbol and source shares one upstream; sources can run in parallel. REST `depth`
   trims to the stream's shape for `'fast'` and `'bbo'`. An unknown source raises
   `ValueError`.
3. `OrderResponse.filled_qty`: perpetuals report the `RESULT` answer's
   `executedQty` (final for `MARKET` and IOC, what filled on arrival for GTC). Spot
   reports `None`: its placement answers before matching.

Behaviour changes:

1. `Book.time` is the snapshot's event time `E` (falling back to the transaction time
   `T`) on REST and WS: partial-depth pushes and REST `depth` are full top-N
   snapshots, current as of `E`. It was `T`.
2. `place_order` reads only `settings['aster']` and ignores other venues' keys, so one
   merged settings dict works everywhere. Before, any non-empty settings raised
   `NotImplementedError`. Cancellations with an `aster` key still raise it.

IOC orders and `filled_qty` are verified by unit fixtures only, not live (testnet
included); the perpetual `filled_qty` relies on the documented `RESULT` semantics.
The depth sources had a 10-second public mainnet smoke check.

The SDK floor rises to 2.17.0, whose `Settings` declares the `aster` key and whose
`OrderResponse` declares `filled_qty`. Upgrade the SDK and this adapter together.

Release qualification on 2026-10-09 passed the read suites and market
consistency. Committed evidence under `release-evidence/aster/` matches pinned
Catalogue `1851660ac2bed8243dd9ce9c7297fe05c7130973`; offline release
verification passes. This adapter release follows SDK 2.17.0 publication.
