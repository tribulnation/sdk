# tribulnation-aster 0.16.0

Requires SDK >=4.2.0 (`POSITION_LIMIT_TTL`, [ADR 0069](../../../dev-docs/adr/0069-position-limits-shared-by-default.md); `PerpPosition.liquidation_price`, [ADR 0068](../../../dev-docs/adr/0068-perp-position-liquidation-price.md)) and typed-aster >=0.7.0, unchanged.

Changed:

1. `perp_position()` carries Aster's `liquidationPrice` as `liquidation_price` (`None` when flat or named `0`).
2. `remaining_position_limit()` shares its reads by default (`ttl` 30 s): the bracket cap, position and leverage come from the all-symbol `positionRisk`, shared by every symbol, with no futures-account read.
3. The per-symbol open-interest allowance (`remainingOpenableNotionalValue`, weight 50) is shared per symbol and leverage for 15 minutes whatever the caller's `ttl`, and requests of all symbols together are spaced 30 s apart; a free turn goes to the oldest answer asked for. Until a symbol's allowance is first read, its open-interest bound is unknown. `available_notional` reads it the same way.
4. A `-5018` refusal drops the shared `positionRisk` and marks the symbol's allowance stale.

Every other method is unchanged.

Release qualification on 2026-11-19 passed the read suites and market consistency.
Committed evidence under `release-evidence/aster/` matches pinned Catalogue
`e3ad9fbd6cd49fb84855c3d3fccbe9f1936a13f1`; offline release verification passes. This adapter
release follows SDK 4.2.0 publication.
