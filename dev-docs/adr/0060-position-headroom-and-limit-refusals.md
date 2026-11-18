# ADR 0060: Position headroom, and position-limit refusals as typed errors

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; builds on [0041](0041-venue-notional-caps.md) and
   [0043](0043-order-rejected.md); implemented for Aster and Hyperliquid, not
   release-verified
2. Date: 2026-11-16

## Context

On 2026-11-16 a hedger routed every hedge of a dYdX maker to Aster, where each was
refused with `-5018` "You've reached the maximum notional value limit for this symbol":
the account's leverage bracket capped the position, although Aster reported $2.9k of
free collateral. The hedges fell back to venues trading ~35 bps worse. The same day
Hyperliquid refused takers on SAGA and RESOLV with "Cannot increase position when open
interest is at cap", a market-wide cap its `perpsAtOpenInterestCap` lists.

Strategies size openings by free collateral. Neither cap shows there: the venue's
`available_notional()` (ADR 0041) folds Aster's caps in, but without a direction and
mixed with collateral, and Hyperliquid's leaves them out. The refusals arrived as a
plain `OrderRejected`, which callers cannot tell from a post-only that would cross, so
they retried into the same wall.

## Decision

1. `MarginMarket.position_headroom(ttl)` returns `PositionHeadroom(long, short)`: the
   notional, in quote units at the venue's mark, by which a long (or short) position may
   still grow beyond closing the other direction. Closing is never limited. `None` is a
   direction without a known limit: unknown, treated as unlimited. Free collateral is
   left out; callers bound openings by the smaller of the two.
2. The default answers `None` both ways. Venues override it from limits they publish and
   the SDK reads live:
   1. Aster: the bracket's `maxNotionalValue` at the current leverage less the position
      held in each direction, bounded by `remainingOpenableNotionalValue` (uncapped at
      `-1`).
   2. Hyperliquid: nothing either way while `perpsAtOpenInterestCap` lists the coin
      (prefixed or not on a HIP-3 dex); otherwise the margin table's bound at the
      position's leverage (the `lowerBound` of the first tier whose `maxLeverage` is below
      it) less the position in each direction; `None` when no tier binds. A flat coin is
      bounded at its `maxLeverage`, the tightest bound any setting has. The
      per-user `activeAssetData.maxTradeSzs` counts free margin too, so it is not used.
3. `PositionLimitExceeded(OrderRejected)`: the venue refused the order because it would
   take the position past a limit. `OpenInterestCapped(PositionLimitExceeded)`: that
   limit is the market's open-interest cap. Both are `OrderRejected`, so existing
   handlers keep working; both are in the gateway's exception table.
   1. Aster raises `PositionLimitExceeded` for `-5018`. `-2027` is not mapped: Aster
      answers it for a leverage setting above the symbol's maximum (ADR 0055).
   2. Hyperliquid raises `OpenInterestCapped` for an order error naming "open interest"
      (`PositionIncreaseAtOpenInterestCap`, `PositionFlipAtOpenInterestCap`,
      `TooAggressiveAtOpenInterestCap`, `OpenInterestIncrease`, and the observed "Cannot
      increase position when open interest is at cap"), and `PositionLimitExceeded` for
      `PerpMaxPosition` ("margin tier limit").
4. The gateway carries it as `position_headroom` / `PositionHeadroomReq` and
   `PositionHeadroomResp`, without a protocol version change, like `replace_orders`.

## Alternatives considered

1. Fold the caps into `available_notional()` on every venue (ADR 0041's route). It has
   no direction, so a position at its cap reads zero for the closing side too, and the
   figure mixes a slowly moving cap with fast-moving collateral that callers already
   track and lease separately.
2. A single `max_position_notional`. Hyperliquid's open-interest cap and Aster's
   remaining allowance are not position maxima; headroom expresses all three.
3. Classify refusals with a reason attribute on `OrderRejected`: callers would branch on
   attributes rather than `except` clauses (as ADR 0043 argued).

## Consequences

1. Reading every market's headroom of an account at once costs a fixed number of
   requests, not one per market (amended 2026-11-18, after polling one market per
   strategy every 10 s had Aster ban the host's IP within a minute):
   1. Aster: the all-symbol `positionRisk` read, shared by every symbol, and the
      symbol's `remainingOpenableNotionalValue` (public, one symbol per request). Each
      allowance answer is reused for 10 minutes whatever the caller's `ttl` (it is
      market-wide and moves slowly), and all symbols of a client together send at most 3
      back to back, then 3 a minute (`RequestBudget`): 30 symbols every 10 minutes. A symbol over budget keeps its
      last answer, `None` before the first; a position-limit refusal drops it.
   2. Hyperliquid: `clearinghouseState` and the public `perpsAtOpenInterestCap`, each
      shared by every coin of a dex. The leverage is the open position's, so no
      per-coin `activeAssetData` read.
   Callers still choose how often to read: one reader per account, not per strategy.
2. Other venues answer `None` until they adopt it. What they publish (2026-11-16):
   Lighter a market-wide `open_interest_limit` beside `open_interest`; dYdX
   `openInterestLowerCap`/`UpperCap` (margin scaling, not a hard cap); Bitget position
   tiers and an open-interest limit endpoint; Kraken Futures `maxPositionSize` per
   instrument; margin.trade nothing found.
3. A gateway older than its client does not decode `position_headroom` and logs it as
   malformed without replying: upgrade gateways with or before clients, and bound the
   call with a timeout on the client side.
4. A client older than its gateway decodes the new refusals as a plain `Exception`.
