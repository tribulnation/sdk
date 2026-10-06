# ADR 0036: SDK roots have no implicit accounts

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted
2. Date: 2026-10-06

## Context

`MarketSDK` and `EarnSDK` merged a module-level `DEFAULT_ACCOUNTS` table of
credential-free accounts beneath the caller's own (`all_accounts`). `WalletSDK`
carried the same mechanism with an empty table; `ReportSDK` never had it.

1. A bare `MarketSDK()` listed twelve venues in `venues()` and `all`, whether or
   not their adapter packages were installed. `all` constructs every listed venue,
   so it raised `ImportError` unless all twelve adapters were present, and the
   gateway advertised venues it could not build.
2. A missing or misnamed `[accounts.<venue>]` table silently fell back to a public
   account. Credentialed calls then failed far from the configuration mistake.
   Qualification already had to guard against exactly this.
3. The three tables disagreed (twelve, two and zero venues, with Coinbase
   deliberately excluded), so which venues "just work" was a per-surface,
   per-venue fact users had to learn.

## Decision

SDK roots contain exactly the accounts they are given. `DEFAULT_ACCOUNTS` and
`all_accounts` are removed from `MarketSDK`, `EarnSDK` and `WalletSDK`; `accounts`
is the single source for `venue()`, `venues()` and `all`. An unconfigured venue
raises `ValueError`, never a fallback.

Credential-free use is configured like any other account, e.g.
`MarketSDK({'hyperliquid': accounts.Hyperliquid(public=True)})` or `public = true`
in `sdk.toml`. Whether a surface's methods then work without credentials remains
the venue's `impl.toml` `auth` declaration.

`sdk-dev test consistency` now requires `--accounts`, like `sdk-dev test surfaces`,
and account selection considers configured accounts only. The published support
matrix keeps its `defaultVenues` key (derived from `auth = false`, never from the
removed tables) for site compatibility.

Release this as SDK 2.11.0, following the minor-version precedent of 2.10.0 for
breaking changes. Adapters do not subclass or call the removed members, so their
SDK floors are unchanged.

## Alternatives considered

1. Removing only Market's defaults: fixes the worst cases but leaves Earn's two
   implicit venues and an inconsistent rule across surfaces.
2. Keeping defaults but filtering to installed adapters: fixes `ImportError` but
   keeps silent fallback for misconfigured accounts.
3. A `public(*venues)` constructor on each root: keeps the quickstart shorter, but
   adds public API, another hand-maintained venue list, and implies a per-venue
   notion of "public" that is really per surface and method (`impl.toml` `auth`).

## Consequences

`MarketSDK()`, `EarnSDK()` and `WalletSDK()` are now empty. Callers relying on
implicit venues must list them in `sdk.toml` or construct the accounts explicitly; `all_accounts` callers use `accounts`. Known
internal consumers (Terminal) already configure every account explicitly.

Shared SDK source and qualification tooling change, so every venue in the SDK
release scope requires fresh read-suite and consistency evidence (ADR 0033).
Tracked qualification accounts were already explicit, so recorded coverage is
unchanged.
