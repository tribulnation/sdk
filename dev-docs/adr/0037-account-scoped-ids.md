# ADR 0037: Account-scoped market and exchange IDs

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: proposed; implemented, not release-verified
2. Date: 2026-10-07

## Context

The user docs address markets as `<account_id>:<exchange_id>:<market_id>`, and
`TradingMarkets` routes by the account key. The base classes nevertheless built
`Market.id` and `Exchange.id` from `venue_id`, which venues hard-coded as their
mainnet venue name (dYdX testnet markets reported `'dydx'`). A venue never learned
the key it was opened under, so with `MarketSDK({'hl': accounts.Hyperliquid(...)})`
the market `hl::ETH` reported `hyperliquid::ETH`: the ID did not resolve through
`sdk.market(id)`, and two accounts on one venue reported identical IDs.

## Decision

1. `TradingVenue`, `Exchange` and `Market` declare two abstract properties:
   `account_id`, the key of the account the object was opened under, and
   `venue_id`, the venue it trades on. `Market.id` is
   `<account_id>:<exchange_id>:<market_id>`, `Exchange.id` is
   `<account_id>:<exchange_id>` and `TradingVenue.id` is `account_id`.
2. `venue_id` is typed `VenueId`, a `Literal` in `tribulnation.sdk.impl.accounts`
   listing every trading venue with each testnet as a separate venue
   (`'dydx'`, `'dydx_testnet'`, ...). It equals the `venue` of the account the
   venue was built from: venues built for a testnet report the testnet variant.
   EVM chains are not trading venues and are not in `VenueId`.
3. The account key is plumbed explicitly. `MarketSDK` passes `account_id=<key>` to
   each venue's constructor (`HyperliquidMarket.http(..., account_id='hl')`). Each
   adapter stores it, with its `venue_id`, on the context object its venue already
   shares with its exchanges and markets (`Shared`, or the market `Cache` for
   Bybit and Bitget), and exposes both as ordinary properties on the adapter's
   common mixin. There are no subclass hooks, wrappers or hidden attributes.
4. A venue built directly, outside a root SDK, defaults its `account_id` to its
   `venue_id`, so its IDs are unchanged.
5. Trading accounts derive from `VenueAccount`, which declares `venue: VenueId`;
   each account class narrows it to its own venues. Accounts are frozen dataclasses,
   which also lets the narrowing type-check.
6. Gateway proxies keep the account-based address as `id` and report the venue the
   gateway-side object reports as `venue_id`, learned in the existing exchange
   resolution round trip or a `venue` request. Every gateway request addressing a
   venue carries the account key as `account_id`; replies carry `venue_id` as a
   validated `VenueId`. Client and gateway are upgraded together.

## Alternatives considered

1. Base-class magic: wrapping the factory methods (`exchange`, `market`, ...) at
   subclass creation to stamp the caller's account key on returned objects.
   No adapter changes, but behavior hidden from the code a reader opens, a
   mechanism that silently skips any factory not on its list, and state outside
   dataclass fields. Rejected in review.
2. Rewriting IDs only in `TradingMarkets` routing: objects obtained from
   `sdk.venue(...)` and then scoped down would still report the venue.
3. A concrete `account_id` default (`venue_id`) on the base classes: fewer edits,
   but an adapter that forgets to plumb the key fails silently.

## Consequences

Accounts keyed by their venue (`[accounts.hyperliquid]` with
`venue = "hyperliquid"`) report the same IDs as before. Any other key now leads the
IDs, for example `bitget_uta`, `deribit_public` or `hyperliquid_testnet`, which
previously reported the venue. Consumers that derived the venue from an ID prefix
must read `venue_id`; consumers comparing `venue_id` to a mainnet name must expect
the testnet variant on testnets.

Every implementation of the abstract classes, including test doubles, must provide
`account_id` and a `VenueId`-typed `venue_id`. Venue-keyed `Settings` keep their
per-package keys (`{'hyperliquid': {...}}`), which apply on mainnet and testnet
alike. Assigning to an account field after construction now raises.
