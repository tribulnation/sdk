# ADR 0039: Venue notional caps in available notional

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; amends [ADR 0038](0038-account-market-leverage.md)
2. Date: 2026-10-08

## Context

ADR 0038 gave `available_notional()` a default of free collateral times `leverage()`,
and said neither that default nor a venue's own figure applies notional caps beyond
what the leverage value already reflects. Aster publishes two caps that bound how much
an account can open regardless of its free balance: the leverage bracket's notional cap
at the configured leverage (a position row's `maxNotional`), and a symbol-wide
open-interest allowance (`remainingOpenableNotionalValue`, `-1` when uncapped). Ignoring
them overstates capacity whenever either binds, which is the case `available_notional()`
exists to answer before an order is sized.

## Decision

1. A venue override of `available_notional()` may take the minimum of the
   leverage-based figure and native notional caps the venue publishes for the account
   and market, provided each cap is read live and documented in the venue's docs.
2. A cap on total position size is applied as the room left in the same direction:
   the cap less the current position's absolute notional, floored at zero. Reducing or
   reversing a position is not modelled.
3. The SDK default and ADR 0038's other decisions are unchanged: the default applies
   no caps, and fees are still not subtracted.
4. Aster applies both caps above. Its free balance is the account's
   `availableBalance` in either margin mode, because new isolated margin is drawn from it.

## Alternatives considered

1. Keep caps out of `available_notional()` and expose them separately. Rejected for
   now: every caller sizing an order would need to combine them, and no second venue
   needs a separate cap read yet.
2. Model reductions and reversals. Rejected: the method has no side argument, and the
   same-direction room is the conservative answer.

## Consequences

1. Aster's `available_notional()` can be lower than free collateral times leverage, and
   costs one extra public request.
2. Other venues are unaffected until they publish and adopt comparable caps.
3. Live verification is a read-only mainnet check; the read suites do not call
   `available_notional()`, so release evidence does not attest it.
