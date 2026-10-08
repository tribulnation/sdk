# ADR 0038: Account-scoped perpetual market leverage

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; implemented, not release-verified; amended by
   [ADR 0041](0041-venue-notional-caps.md)
2. Date: 2026-10-08

## Context

Sizing a perpetual order needs the multiple of free collateral the account can open
at. Each venue's `available_notional()` computed one internally, inconsistently:
Hyperliquid multiplied by the asset's `maxLeverage` although the account's per-asset
setting is often lower, dYdX by `1 / effective IMF`, Lighter by the configured
fraction, and Aster did not implement it at all. Callers could not read the multiple
itself, so they could not size against a balance other than the one
`available_notional()` happened to read.

The value is account-specific (Hyperliquid, Lighter and Aster store a per-market
setting), so it does not belong in the public `rules()` (ADR 0002 keeps account reads
out of them). Nor does it belong in `Collateral`: a collateral bucket is shared by many
markets, and the exchange-level bucket has no market at all.

## Decision

1. `PerpMarket.leverage(*, refetch=False) -> Decimal` returns the multiple of free
   collateral the account can open as notional on that market: opening `n` of notional
   needs `n / leverage` of collateral. It is cached like `fees()`; `refetch=True`
   bypasses the cache. The base implementation raises `NotImplementedError`.
   `PerpExchange`, `TradingVenue` and `TradingMarkets` forward it for a market ID, and
   the gateway carries it as a `leverage` request.
2. Leverage is perpetual-only. Spot markets trade on their cash balance and the SDK
   has no spot margin, so a spot leverage of `1` would only restate that.
3. `available_notional()` gets defaults: `collateral().free_collateral` on `Market`
   (spot: the free quote balance) and `collateral().free_collateral * leverage()` on
   `PerpMarket`, with the market's mode-aware collateral. The perpetual default reads
   `leverage()` first, so an unsupported leverage raises before any account read.
4. A venue keeps its own `available_notional()` only where it has a more precise
   figure, and documents why. Hyperliquid and Lighter keep one because isolated
   positions are funded from the account's cross pool, not their own bucket. Venues
   without `leverage()` keep their existing `available_notional()` unchanged.
5. Neither figure subtracts fees or applies notional caps beyond what the venue's
   leverage value already reflects.

## Alternatives considered

1. A `leverage` field in `Rules`. Rejected: the value depends on the account, and
   rules must stay account-free.
2. A field in `Collateral`/`PerpCollateral`. Rejected: buckets span markets with
   different leverages, and `PerpCollateral.leverage` already means used leverage.
3. `Market.leverage()` returning `1` on spot. Rejected as an unverifiable claim for
   venues with spot margin that the SDK does not model.

## Consequences

1. Implemented for Hyperliquid, dYdX, Lighter and Aster. Bybit's market support
   becomes `partial` because it does not implement `leverage()`.
2. Hyperliquid's perpetual `available_notional()` now uses the account setting rather
   than `maxLeverage`, so it can be lower than before. Aster gains a perpetual
   `available_notional()`.
3. Implementations subclassing the SDK's base classes need the SDK release that adds
   `leverage()`; impl floors must be raised in the same release.
4. Live leverage reads are not yet part of the read-only qualification suites.
