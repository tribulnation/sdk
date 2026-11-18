# ADR 0062: Remaining position limit, and position-limit refusals as typed errors

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; builds on [0041](0041-venue-notional-caps.md),
   [0042](0042-read-only-account-method-qualification.md),
   [0043](0043-order-rejected.md) and [0056](0056-market-kind-aware-support.md);
   implemented for Aster and Hyperliquid, not release-verified
2. Date: 2026-11-16; amended 2026-11-17 (renamed from "position headroom", added to the
   contract and to account-read qualification)

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

Such limits are the rule, not an Aster or Hyperliquid quirk. A survey of 15 perpetual
venues (2026-11-17) found 14 that publish them, of three kinds, several venues
combining them:

1. Leverage-dependent tiers, where higher leverage allows a smaller position: Binance,
   Aster, Bybit, Bitget, KuCoin, MEXC, GRVT, Hyperliquid, Extended, Kraken Futures.
2. Market-wide open-interest caps: Hyperliquid, Lighter, Nado, RISEx, Extended, Bitget.
3. A static maximum position: Kraken Futures, GRVT, RISEx, Extended, Bitget.

Common libraries do not cover this: ccxt, Nautilus and Hummingbot model per-order size
limits and static tier tables only, not what is left to an account now. Some venues
compute a per-account maximum themselves (Hyperliquid `activeAssetData.maxTradeSzs`,
KuCoin's, Nado `max_order_size`, Bitget `maxOpenPosAvailable`), but those figures
include free margin, which callers already bound through `available_notional()`.

## Decision

1. `MarginMarket.remaining_position_limit(ttl)` returns
   `RemainingPositionLimit(long, short)`: per direction, the notional, in quote units at
   the venue's mark, by which a long (or short) position may still grow, beyond
   closing the other direction, under the venue's position limits: a static maximum
   position, leverage-dependent tiers and market-wide open-interest caps. Closing is
   never limited. `None` is a direction without a known limit: unknown, treated as
   unlimited. Free collateral is left out; callers bound openings by the smaller of
   this and `available_notional()`. The figure holds at the account's current
   leverage, and near an open-interest cap it is racy: other accounts take the same
   room.
2. The default answers `None` both ways. Venues override it from limits they publish and
   the SDK reads live:
   1. Aster: the bracket's `maxNotional` at the current leverage less the position held
      in each direction, bounded by `remainingOpenableNotionalValue` (uncapped at `-1`).
   2. Hyperliquid: nothing either way while `perpsAtOpenInterestCap` lists the coin
      (prefixed or not on a HIP-3 dex); otherwise the margin table's bound at the
      account's leverage (the `lowerBound` of the first tier whose `maxLeverage` is below
      it) less the position in each direction; `None` when no tier binds.
   3. Venue-computed maxima that include free margin (see Context) are not used.
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
4. The gateway carries it as `remaining_position_limit` / `RemainingPositionLimitReq`
   and `RemainingPositionLimitResp` (field `limit`), without a protocol version change,
   like `replace_orders`.
5. It is a Market contract method (`docs/contract/market.yml`), `kind: perp`, routed
   like `available_notional` through `TradingMarkets`, `TradingVenue` and
   `PerpExchange` (`sdk.remaining_position_limit(market_id)`). Under ADR 0056 a `full`
   venue serving perpetuals supports it through the default; `partial` venues list it
   where they declare the other margin account reads (Aster, Bitget, Bybit,
   Hyperliquid, margin.trade). Each venue's documentation says what it reads, or that
   it reads no limits and answers `None` both ways.
6. It is an account read of release qualification (ADR 0042), checked as finite and
   non-negative per direction, or `None`. Each `[qualification.market]` serves it in
   the same credential mode as `available_notional`, and Bitget `usdc` lists it as
   unsupported with its other account reads.

## Alternatives considered

1. Fold the caps into `available_notional()` on every venue (ADR 0041's route). It has
   no direction, so a position at its cap reads zero for the closing side too, and the
   figure mixes a slowly moving cap with fast-moving collateral that callers already
   track and lease separately.
2. A single `max_position_notional`. Hyperliquid's open-interest cap and Aster's
   remaining allowance are not position maxima; a remaining amount expresses all three.
3. Classify refusals with a reason attribute on `OrderRejected`: callers would branch on
   attributes rather than `except` clauses (as ADR 0043 argued).
4. The name `position_headroom` / `PositionHeadroom`, as first proposed. "Position
   limit" is the industry's term for these caps, and `remaining_position_limit` forms
   one family with `PositionLimitExceeded` and `OpenInterestCapped`.
5. Publish venues' static leverage tiers as data, so callers could plan a leverage
   change. Deferred to a separate decision: it answers another question (what another
   leverage would allow), and most venues' tiers need reads of their own.

## Consequences

1. Aster's figure costs the shared `positionRisk` and futures-account reads plus one
   public request; Hyperliquid's the shared `clearinghouseState` and `activeAssetData`
   reads plus one shared, public `perpsAtOpenInterestCap` read per dex.
2. Other venues answer `None` until they adopt it; a `None` direction is not evidence
   that no limit exists. What they publish (2026-11-17): Lighter a market-wide
   `open_interest_limit` beside `open_interest`; dYdX `openInterestLowerCap`/`UpperCap`
   (margin scaling, not a hard cap); Bitget position tiers and an open-interest limit
   endpoint; Kraken Futures `maxPositionSize` per instrument; Extended
   `maxPositionValue` and `openInterestLimit`; GRVT `max_position_size`; RISEx
   `max_position_size` and `open_interest_limit`; Nado `max_open_interest_x18`;
   margin.trade nothing found.
3. A new qualification read changes live qualification, so every venue in a release's
   scope needs fresh read evidence (ADR 0033); the shared SDK change requires it anyway.
4. A gateway older than its client does not decode `remaining_position_limit` and logs
   it as malformed without replying: upgrade gateways with or before clients, and bound
   the call with a timeout on the client side.
5. A client older than its gateway decodes the new refusals as a plain `Exception`.
