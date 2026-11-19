# ADR 0068: The venue's estimated liquidation price on `PerpPosition`

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; builds on [0032](0032-sdk-gateway.md) and
   [0042](0042-read-only-account-method-qualification.md); implemented for Hyperliquid
   (HIP-3 dexes included), Aster, Lighter and GRVT, not release-verified
2. Date: 2026-11-19

## Context

On 2026-11-18 an isolated position on a Hyperliquid HIP-3 market (`xyz`) was
liquidated after a 6 % move. The strategy holding it read its positions through the gateway with
`perp_position()`, which returned only `size` and `entry_price`, so nothing it read
said how close the position was to liquidation.

The Market docs ([Collateral & Risk](../../docs/market/collateral.md)) had ruled a
per-position liquidation price out: not every venue can give one, and the bucket's
`maintenance_ratio` answers the same question. That holds for collateral, whose fields
are never `None`, but it leaves the question unanswered where callers ask it. A
`maintenance_ratio` is per bucket, so on a cross bucket it says how far the account is
from liquidation, not at what price this position would go; turning it into a price
needs the mark, the maintenance fraction of every position in the bucket and how each
moves, which is the venue's own computation.

Venues publish that computation per position:

1. Hyperliquid: `clearinghouseState` `liquidationPx`, per dex, `null` where the
   collateral covers any move (mainnet 2026-11-19: cross longs on `xyz` read `null`,
   cross shorts and isolated positions a price).
2. Aster: `positionRisk` `liquidationPrice`, `0` on flat rows and where none.
3. Lighter: the account's positions' `liquidation_price`, `0` on flat entries and covered
   cross longs, a price (sometimes far away) on cross shorts and isolated positions.
4. GRVT: `positions` `est_liquidation_price`, `0.0` on a covered cross long, a price on
   isolated positions.

Every venue above writes "none" as `0` or `null`; none documents the rule it applies,
and under cross margin the price moves with the account's other positions and
collateral.

## Decision

1. `PerpPosition` gains `liquidation_price: Decimal | None = None`: the venue's
   estimated liquidation price in quote units, compared with its mark, passed through
   unchanged. `None` means flat, a venue naming no price (its `0` or `null`), or an
   adapter that does not read one. A positive value is never invented: the SDK does not
   derive one from margins.
2. Hyperliquid (every dex), Aster, Lighter and GRVT read it from the reads
   `perp_position()` already makes; no request is added. Other venues keep `None`
   until an adapter reads its venue's figure.
3. The field is optional on the gateway wire: `perp_position` replies carry it, a
   gateway predating it omits it, which decodes as `None`, and a client predating it
   ignores it. The protocol stays `tribulnation-gateway.v2`, as its versioning rule
   asks for an added optional reply field.
4. Account-read qualification checks its shape: `None` or a finite positive Decimal,
   and `None` on a flat position. Its value is not checked against the venue's UI or a
   recomputation.
5. Collateral stays as it is: no liquidation price on `PerpCollateral`, whose fields
   remain non-`None`.

## Alternatives considered

1. Derive a price from `perp_collateral()` and the mark. It is exact only for an
   isolated bucket with a known maintenance fraction, and would differ from the price
   the venue liquidates at whenever its rule differs (tiers, fees, funding accrual).
2. Put it on `PerpCollateral`. A cross bucket has no single price, and collateral's
   contract is that every field is known on every venue.
3. A separate `liquidation_price()` method. A second request (or shared read) per
   question, and a new gateway message kind, a version change for clients, for a
   figure every venue returns beside the position.
4. A required field. Venues without a figure would have to invent one, and old
   gateways would fail to decode.

## Consequences

1. Callers see the venue's estimate where they already read positions, including
   through the gateway, with no new call. They must treat it as an estimate that moves
   under cross margin and as absent wherever it is `None`.
2. An adapter setting the field requires the SDK release that adds it: its
   `tribulnation-sdk` floor rises with it, since constructing `PerpPosition` with the
   field fails on an older SDK.
3. The four adapters change their `perp_position()` read, so their next releases need
   change-scoped live evidence (ADR 0033); the SDK change alone, and gateway peers on
   either side of it, need none.
4. Lighter's far-off prices on small cross shorts in large accounts pass through as the
   venue reports them.
