# tribulnation-aster 0.11.1

Requires SDK >=2.17.0 and typed-aster >=0.5.0. An account event type Aster does not
document no longer ends the fills stream.

Fixes:

1. `trades_stream` survives user-data events the client does not model. On
   2026-10-15 Aster pushed an undocumented `FUND_CHANGE_WS` event, which failed
   validation, ended the shared account stream and failed every subscriber on the
   account at once. typed-aster 0.5.0 delivers such events as an unknown-event type,
   and the perpetual and spot fill streams skip them, so fills after one are still
   delivered. Known events are still validated strictly.

The typed-aster floor rises to 0.5.0, which defines the unknown-event types. The SDK
floor is unchanged.

Release qualification on 2026-10-15 passed the read suites and market
consistency. Committed evidence under `release-evidence/aster/` matches pinned
Catalogue `1851660ac2bed8243dd9ce9c7297fe05c7130973`; offline release
verification passes. The recorded dependency pins differ from the previous
evidence only in `typed-aster` (0.4.0 to 0.5.0).
