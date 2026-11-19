# tribulnation-risex 0.1.0

First release. Requires SDK >=4.1.0 and typed-risex >=0.1.1 (accepts unsettled funding rows' empty `funding_rate_8h`).

1. Market: RISEx perpetuals (support `full`). Every account read is public, keyed by the account's `address`; a registered signer (session) key places and cancels orders. Tickers carry no best bid or ask: the venue publishes none.
2. `set_leverage(leverage)`, and `remaining_position_limit()` from `max_position_size` less the position, bounded by the open-interest limit.
3. Candles pass RISEx's unordered native OHLC through as an accepted limitation ([ADR 0061](../../../dev-docs/adr/0061-risex-unordered-native-candles.md)).
4. Report: `snapshot()` from the account's address.
5. Accounts `risex` and `risex_testnet` in the SDK.

Release qualification on 2026-11-18 passed the read suites and market consistency.
Committed evidence under `release-evidence/risex/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows SDK 4.1.0 publication.
