# ADR 0058: Default `delta()` and `hold()` on spot and margin markets

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed
2. Date: 2026-10-29
3. Builds on: [ADR 0051](0051-spot-perp-market-types-collateral-ids.md)

## Context

A hedging strategy asks two questions of every market it trades: its exposure to the
base asset, and what an order would hold while it rests (which collateral, how much).
ADR 0051 gave each market kind the reads that answer them, but differently: spot has
`balances()` and `collateral_ids()`, margin markets `position()`, `collateral_id()` and
`leverage()`. Every strategy re-derived the same per-kind arithmetic, including the
opening/closing split of a margin order.

## Decision

1. `SpotMarket` and `MarginMarket` gain two concrete default methods, composed only of
   existing ones:
   1. `delta(*, ttl=None) -> Decimal`: signed base-unit exposure.
      Spot: `balances().base.total`, holds included. Margin: `position().size`.
   2. `hold(*, qty, price, ttl=None) -> Hold`, with
      `Hold(collateral_id: str, amount: Decimal)` frozen, `amount` in the collateral's
      own units. Spot: a buy holds `qty * price` on `collateral_ids().quote`, a sell
      `|qty|` on `collateral_ids().base`. Margin: `opening * price / leverage()` on
      `collateral_id()`, where `opening` is what of `|qty|` exceeds what the order closes
      of `position().size`; a closing order holds nothing and reads no leverage.
   3. Fees are not included. `ttl` goes to every position, balance and leverage read.
2. `Market` declares both too, so a strategy holding a plain `Market` calls them without
   narrowing to `SpotMarket | MarginMarket`. There they raise `NotImplementedError`:
   venues not yet migrated to the 0051 hierarchy subclass `Market` directly, so an
   abstract declaration would stop them instantiating.
3. They are not abstract, so venue packages already released against 3.x keep working
   unchanged. Venues may override them with a native figure.
4. No gateway protocol change: through `ProxySpotMarket`/`ProxyPerpMarket` the defaults
   compose the proxied reads.

## Alternatives considered

1. Abstract methods implemented per venue. Rejected: every released venue package would
   stop instantiating, for arithmetic that is the same everywhere.
2. Including fees in `hold()`. Rejected for now: the fee asset and whether a venue
   reserves fees up front differ per venue; callers that need it add `fees()` themselves.
3. Root-level routers (`sdk.delta(market_id)`). Deferred: callers hold market objects.

## Consequences

1. Strategies can size reservations per collateral ID without branching on market kind.
2. `hold()` on margin reflects the position at read time; an order placed against a
   position that moves before it rests may hold more than computed.
