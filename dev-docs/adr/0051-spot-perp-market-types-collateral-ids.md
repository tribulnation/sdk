# ADR 0051: Spot and margin market types, and collateral IDs

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed
2. Date: 2026-10-24
3. Amends: [ADR 0009](0009-catalogue-owned-asset-identity.md) (spot rules name their
   assets) and [ADR 0038](0038-account-market-leverage.md) (the spot
   `available_notional()` default is removed).

## Context

`Market` carries perpetual-shaped account methods, so spot markets answer them with
stand-ins: `collateral()` is the quote balance, `position()` the total base balance
including what open orders hold, and `available_notional()` covers buys only. There
is no free-base figure for sizing a spot sell. Exchange-wide
`collateral('<acct>:spot')` raises `NotImplementedError`, which crash-loops the
strategies' collateral manager so takers and makers never start.

On unified accounts (Hyperliquid) the perpetual cross pool *is* the spot balance of
the dex's collateral token. Strategies see two buckets, so a spot manager and a perp
manager can each reserve the same USDC. Spot and perpetual markets are told apart only
by `isinstance`, and spot rules do not say which assets a pair trades.

## Decision

1. **Hierarchy.** `Market` keeps book, trades, orders, rules and fees, and loses
   `collateral()`, `position()` and `available_notional()`. It splits into
   `SpotMarket` and `MarginMarket`; `PerpMarket(MarginMarket)` adds funding and
   index. An `OptionMarket(MarginMarket)` can follow later without moving methods
   again. Exchanges split the same way into `SpotExchange` and `PerpExchange`;
   exchange-wide `collateral()` exists only on `PerpExchange`. There is no
   all-assets `SpotExchange.balances()` for now.
2. **Telling them apart.** `is_spot(m) -> TypeIs[SpotMarket]` and
   `is_perp(m) -> TypeIs[PerpMarket]` (and the same for exchanges) narrow the static
   type; methods cannot narrow `self`. Every market and exchange also has
   `kind: Literal['spot', 'perp']`.
3. **Spot.** `SpotMarket.rules()` returns `SpotRules`, whose `base` and `quote` are
   the venue-native asset IDs (the IDs the venue's `[ids].asset` form names).
   Perpetual rules get no such fields: a contract's denomination need not be its
   collateral (ADR 0009's reason still holds there). `balances()` returns
   `SpotBalances(base: Balance, quote: Balance)` with `Balance(total, free)`, where
   `free` excludes what open orders hold. `collateral_ids()` returns the base and
   quote collateral IDs.
4. **Margin.** `MarginMarket` has `collateral()` (a `PerpCollateral`, mode-aware,
   for liquidation distance), `position()`, `leverage()`, `available_notional()` and
   `collateral_id()`: the ID of the money that funds *new orders* on this market.
   `collateral_id()` is async and cached after the first call, like `leverage()`;
   the base implementation raises `NotImplementedError` rather than guess a pool for
   a venue that may be unified.
5. **Collateral IDs** are opaque strings led by the account key, like market IDs:
   a spot asset is `<acct>:<spot exchange>:<venue asset id>` (`hl:spot:USDC`), a perp
   pool is `<acct>:<perp exchange>` (`mt:perp`, or one per perp exchange where a venue
   has several, such as Hyperliquid HIP-3 dexes). Markets sharing money return the
   same ID:
   1. Unified accounts: a perpetual's ID is its collateral token's spot ID. On
      Hyperliquid that is `<acct>:spot:<perp_meta[dex]['collateralToken'] name>`, so
      spot and perp strategies share one ID.
   2. Isolated perpetuals return the pool new margin is drawn from; the isolated
      bucket matters only for liquidation, through `collateral()`.
   3. Separate wallets (Margin Trade, Aster, classic Lighter): spot `<acct>:spot:USDC`
      and perp `<acct>:perp` are distinct.
6. **Resolver.** `sdk.collateral(id) -> Collateral(equity, free_collateral)` accepts
   any collateral ID, generalising today's exchange form. Spot IDs resolve through
   `SpotExchange.balance(asset)` (`equity = total`, `free_collateral = free`), pool IDs
   through `PerpExchange.collateral()`. The old market form
   `collateral('<acct>:<exchange>:<market>')` would collide with spot IDs and is
   removed: use `perp_collateral(<market id>)` or the market's `collateral()`.
   Hyperliquid reads `spot_clearinghouse_state`, free = total − hold.
7. **Breaking release 3.0.0.** The spot stand-ins are removed outright, without
   deprecation shims; the changelog and docs carry the migration. The gateway
   protocol becomes `tribulnation-gateway.v2`, since spot requests change meaning.
8. Margin Trade `fees()` returns the market's `rules().fees`, the rates its fills are
   charged, instead of raising.

How strategies will use this (strats #161, outside this decision): one
`CollateralManager` per collateral ID, keyed by the ID alone with no parameters. A
spot buy reserves on the quote ID, a spot sell on the base ID, a perp order on
`collateral_id()` sized by `leverage()`. Available = the venue's free figure minus the
manager's in-flight reservations; the venue's `free` already excludes resting orders.

## Alternatives considered

1. Keep spot stand-ins and add spot methods beside them (the explainer's one-release
   deprecation). Rejected for 3.0.0: the stand-ins are what strategies misuse, and
   a shim would keep both meanings alive across a breaking release anyway.
2. A `kind` field or method alone. Rejected: it cannot narrow the static type, so
   callers would still cast.
3. A default `collateral_id()` of the exchange pool. Rejected: on a unified venue that
   forgets to override it, it silently recreates the double reservation.
4. Base/quote on every `Rules`. Rejected for perpetuals for ADR 0009's reason.
5. Portfolio margin (spot assets as haircut collateral). Out of scope.

## Consequences

1. Every venue adapter must migrate. The first pass covers Hyperliquid, Margin Trade,
   dYdX, Lighter and Aster; the others keep compiling against plain `Market` (so
   `is_spot` is false and they lose spot account reads through the base type) or
   raise `NotImplementedError` from `collateral_id()` until their second pass.
2. Consumers that called `collateral()`/`position()`/`available_notional()` on a spot
   market, or passed a market ID to `collateral()`, must migrate. Gateway clients and
   the gateway upgrade together.
3. Impl floors rise to `tribulnation-sdk>=3.0.0` in the release that adopts the types.
   Live read suites qualify `balances()` and `collateral_id()` through the resolver;
   acceptance is not release evidence.
