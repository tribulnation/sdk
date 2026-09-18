# ADR 0019: KuCoin public spot and linear perpetual Market support

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; implementation and qualification are tracked separately.
2. Date: 2026-09-18

## Context

SDK #33 defers KuCoin public-market expansion independently of the existing
Wallet/Earn/Report release. The old Market prototype mixed public and private reads,
passed futures lots through as base quantities, and did not map candles or discovery.
Public typed-client probes now establish a narrower, credential-free implementation.

## Decision

1. Add public Classic spot and linear perpetual data, with explicit
   `spot` and `perp` exchange IDs and unmodified native market symbols.
2. Exclude inverse and dated contracts. Linear contract quantities are converted to
   base units with the published multiplier; already-base volume is preserved.
3. Keep private Market methods and trading explicitly unsupported. Market construction
   uses a credential-free client even when private credentials exist for other surfaces.
4. Use public rules without personal fee queries; unqualified combined standard fees
   remain unknown. Perpetual statistics provide index, mark and open interest;
   dedicated next-funding and funding-history methods carry the qualified funding data.
5. Expose all six SDK trade-candle intervals with aware half-open bounds and bounded
   time pagination. Use observed caps of 1,500 spot/200 futures rows; a sparse page
   never terminates a requested time range. Preserve absent periods without synthesis.
6. Funding history preserves inclusive bounds and earliest-available open-start behavior.
   REST depth is bounded to 100 levels; the qualified stream is bounded to five.

## Alternatives considered

- Promote the full old prototype: rejected because it includes unqualified private
  methods and incorrect quantity units for the SDK contract.
- Use the documented 500-row futures candle cap: live responses truncate to 200,
  which would leave silent gaps when advancing 500-candle windows.
- Treat omitted Catalogue exchange metadata as a default: strict consistency requires
  an explicit matching value. Existing KuCoin perpetual entries need a Catalogue
  update to `exchange: perp`; neither omission nor an empty SDK ID satisfies it.
- Require complete historical backfill: deferred because retained data differs by
  product and interval. A successful API read is not an archive completeness claim.

## Consequences

The public MarketSDK default can operate without Futures permissions. Existing private
surfaces retain their own account scope. Native Catalogue gaps remain visible and are
not solved by renaming SDK symbols. New release evidence is required for this expanded
surface. Publication and Terminal rollout remain separate actions.

The [qualification handoff](../kucoin-public-market.md) records endpoint mappings,
observations, limits and version requirements.
