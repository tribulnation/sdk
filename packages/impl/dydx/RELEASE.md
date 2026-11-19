# tribulnation-dydx 0.22.0

Requires SDK >=4.1.0, unchanged, and typed-dydx >=3.8.0 (was >=3.7.0), which wraps the signed `MsgUpdateLeverage` and the chain's per-subaccount leverage query.

Added:

1. `set_leverage()` signs `MsgUpdateLeverage` for the market's CLOB pair and the addressed subaccount, simulating it before broadcast. The chain takes an initial margin fraction in ppm (`1000000 / leverage`), so only leverages with a whole ppm fraction are accepted (`3` is refused, not rounded), from 1 to the market's maximum. Verified on testnet only.

Changed:

1. `leverage()` reads the subaccount's own setting from the chain on every call (behaviour change) and returns `1 /` the larger of it and the market's effective initial margin fraction. It now needs an address: without one it raises `AuthError` instead of answering from public market data.
2. The Market support declaration is `full`.

Every other method is unchanged.

Release qualification on 2026-11-19 passed the read suites and market consistency.
Committed evidence under `release-evidence/dydx/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes.

# tribulnation-dydx 0.21.1

Requires SDK >=4.1.0 (`set_leverage`, `remaining_position_limit` and `to_decimal`, [ADR 0062](../../../dev-docs/adr/0062-remaining-position-limit-and-limit-refusals.md), [ADR 0066](../../../dev-docs/adr/0066-set-leverage-and-leverage-not-set.md)) and typed-dydx >=3.7.0, unchanged.

Changed:

1. The Market support declaration lists `remaining_position_limit` (the SDK default: no limits known). `set_leverage` is not implemented: the typed client does not wrap dYdX's signed `MsgUpdateLeverage` yet.
2. Order quantity and price go through the SDK's `to_decimal` (behaviour change): a `float` input keeps its decimal digits (`0.1` is sent as `0.1`) instead of its binary expansion, which grid checks refused or which reached the wire with 50 digits.

Every other method is unchanged.

Release qualification on 2026-11-18 passed the read suites and market consistency.
Committed evidence under `release-evidence/dydx/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows SDK 4.1.0 publication.
