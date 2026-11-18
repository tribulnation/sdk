# ADR 0066: `set_leverage` and `LeverageNotSet`

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; implemented for Bitget, Aster and Hyperliquid, not release-verified
2. Date: 2026-11-18

## Context

Bitget's unified account lists a symbol's leverage only once the account has set one,
so `leverage()` refuses rather than guess the venue's default (ADR 0064). On
2026-11-17 a live hedge on `bitget:usdt:MORPHOUSDT` failed on every step for that
reason: nobody had set the leverage by hand, and the SDK offered no way to set it. The
refusal arrived as a plain `ValueError`, which callers could not tell apart from
other bad values.

The engine wants a market it has never traded to be configured without a person
setting leverage in the venue's app. The decision of when and to what is the
caller's; the SDK only needs to report the missing setting distinctly and to provide
the call that sets it.

## Decision

1. `LeverageNotSet` (`tribulnation.sdk`, `tribulnation.sdk.core`) is raised by
   `leverage()` when the account has no leverage set on the market and the venue
   applies none by default. It subclasses `Error` and `ValueError`, so code catching
   the earlier `ValueError` keeps working. Bitget raises it; venues that always
   report a setting (their default for unconfigured markets) never do.
2. `MarginMarket.set_leverage(leverage)` sets the account's leverage on one market,
   with root delegations on `TradingMarkets`, `PerpExchange` and `TradingVenue`. It
   takes a positive whole number (`whole_leverage`), raising `ValueError` before any
   request otherwise. It never changes a margin mode: cross where the SDK trades
   cross, isolated only where the account's setting already is isolated or the venue
   allows nothing else. After setting, shared leverage reads are dropped, so the next
   `leverage()` asks the venue.
3. The SDK never calls `set_leverage` on its own, and `leverage()` keeps refusing when
   nothing is set. Applying a default is the caller's policy.
4. Venues:
   1. Bitget: `POST /api/v3/account/set-leverage`, `USDT-FUTURES`, `crossed`, on UTA
      accounts only (Classic raises `NotImplementedError`, like every trading call).
   2. Aster: `POST /fapi/v1/leverage`, under the symbol's leverage lock shared with
      the `-2027` check (ADR 0055); the margin type is left alone.
   3. Hyperliquid: `updateLeverage` on the asset, cross unless the account's setting
      is isolated or the asset is isolated-only (`onlyIsolated`, `marginMode:
      noCross`, as on some HIP-3 dexes).
   4. Kraken Futures: `NotImplementedError`. Cross leverage is the margin schedule's;
      a leverage preference moves the market to isolated margin.
   5. Other venues: the base `NotImplementedError` until implemented.
5. The gateway carries both: a `set_leverage` request (`market_id`, `leverage`) with an
   empty `set_leverage` reply, and `LeverageNotSet` as a typed remote exception.

## Not yet decided

The contract reference (`docs/contract/market.yml`) gets no `set_leverage` entry in
this change. dYdX, Extended, GRVT and Lighter declare `support = "full"` for Market,
which would claim a method they do not implement; adding the entry needs either
those venues' implementations or explicit `partial` lists.

## Alternatives considered

1. Have `leverage()` fall back to a default on Bitget: it would report a number the
   venue never confirmed, and could under-hold (ADR 0064).
2. Have the SDK set a default before a market's first order: the same objection as
   ADR 0055 raised against setting leverage unasked; the choice belongs to callers.
3. Let callers use the typed clients directly: it would not cross the gateway, which
   is how the engine reaches venues.
