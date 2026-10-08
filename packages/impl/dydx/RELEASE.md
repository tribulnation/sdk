# tribulnation-dydx 0.12.0

Requires SDK >=2.12.0. Market, exchange and venue objects expose `account_id`,
the root SDK account key they were opened under, and build their IDs from it;
`venue_id` is the typed venue. Objects built directly keep their current IDs.
`depth()` and `depth_stream()` accept the SDK's venue-keyed `settings`.

`accounts.Dydx` takes a `private_key` as an alternative to a mnemonic, and its
`address` is the account traded for, so dYdX API wallets work with the address
and private key the frontend provides. Requires typed-dydx >=3.6.0.

Breaking: `DydxMarket.new()` without credentials now requires `public=True`,
matching every other venue; missing credentials fail at construction instead of
silently yielding a read-only client. Testnet objects now report
`venue_id == 'dydx_testnet'`. dYdX books carry no timestamp, so `Book.time` is
`None`.

Upgrade the SDK and this adapter together.

Release qualification on 2026-10-08 passed the read suites and market
consistency. Committed evidence under `release-evidence/dydx/` matches pinned
Catalogue `1851660ac2bed8243dd9ce9c7297fe05c7130973`; offline release
verification passes. This adapter release follows SDK 2.12.0 publication.
