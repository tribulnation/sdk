# ADR 0055: Aster lowers leverage only when an order is refused for it

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; amends decision 3 of [0053](0053-shared-account-reads-aster-max-leverage.md); implemented, not release-verified
2. Date: 2026-10-27

## Context

[ADR 0053](0053-shared-account-reads-aster-max-leverage.md) decision 3 set every Aster
symbol's leverage to its maximum (bracket 1's `initialLeverage`) before the symbol's
first order, and again after a `-2027` refusal. The only failure observed is the second
case: Aster lowers a symbol's maximum while the account keeps its old, now too high,
setting, and refuses every order on it with `-2027`.

Raising every traded symbol to its maximum solves nothing that was observed and changes
what nobody asked for: margin use per notional, the liquidation distance and the
notional bracket a position is capped by. It also costs a round trip (brackets and
`positionRisk`) before each symbol's first order.

## Decision

1. `place_order` never reads or sets the leverage before sending an order. The adapter
   never raises a symbol's leverage.
2. On a `-2027` refusal it reads the symbol's current maximum (bracket 1's
   `initialLeverage`) and the current setting (`leverage(ttl=None)`). If the setting is
   above the maximum it sets it to the maximum, forgets the shared `positionRisk`
   answer, logs the change, and resends the order once.
3. One such check per symbol stands for 10 s, under a per-symbol lock, so orders refused
   together share one check and its outcome.
4. If the setting is not above the maximum, the original `OrderRejected` is raised. If
   the check or the change fails, the original `OrderRejected` is raised from that
   failure. Neither case resends the order.
5. This applies to Aster only; other venues keep their behaviour.

## Alternatives considered

1. Keep raising to the maximum before the first order (ADR 0053): see Context.
2. Raise the original refusal without fixing it: every order on the symbol would keep
   failing until someone changed the setting by hand.

## Consequences

- An account's leverage settings are left as the operator set them, except for a symbol
  whose maximum fell below its setting, which is lowered to the new maximum.
- Accepted orders cost no extra request.
- An order refused with `-2027` costs two reads, one change and a resend.
