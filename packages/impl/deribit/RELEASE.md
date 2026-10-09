# tribulnation-deribit 0.6.0

Requires SDK >=2.16.0 and typed-deribit >=0.3.0. `trades_stream` accepts the new
keyword-only `settings` argument of SDK 2.16 (ADR 0044) and ignores it: Deribit
has no trades-stream options. Fills and every other method are unchanged.

The SDK floor rises to 2.16.0, whose `Market.trades_stream` declares `settings`.
Upgrade the SDK and this adapter together.

Release qualification on 2026-10-09 passed the read suites and market
consistency. Committed evidence under `release-evidence/deribit/` matches pinned
Catalogue `1851660ac2bed8243dd9ce9c7297fe05c7130973`; offline release
verification passes. This adapter release follows SDK 2.16.0 publication.
