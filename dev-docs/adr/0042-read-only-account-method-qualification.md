# ADR 0042: Read-only account-method qualification

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; implemented, not release-verified
2. Date: 2026-10-08
3. Amends: [ADR 0013](0013-all-read-suites-release-gate.md) (required market read
   cases), the fee-read decision 7 of [ADR 0039](0039-hyperliquid-hip3-spot-fees.md)
   and consequence 3 of [ADR 0041](0041-venue-notional-caps.md).
   Tracks [issue #182](https://github.com/tribulnation/sdk/issues/182).

## Context

The required market read suite covered public reads only. Account-scoped Market
methods (`fees`, `open_orders`, `trades_history`, `funding_payments`, `position`,
`perp_position`, `collateral`, `perp_collateral`, `leverage`, `available_notional`)
reached release evidence only through Bitget's own suite and, under ADR 0039,
Hyperliquid's address-keyed `fees()`. Every other venue could release adapter changes
to these methods without a live observation, and ADR 0041 recorded that
`available_notional()` was not attested at all.

These reads need an account, and venues differ in what that account must be: an
address (dYdX, Hyperliquid), a read-only token (Lighter, ADR 0040) or private
credentials. Some product lines declare no account support at all (Binance USD-M,
Kraken and MEXC perpetuals, Bitget USDC), which the surface-level `methods` list in
`impl.toml` cannot express, and one Bitget mode has no margin figures (ADR 0008).

## Decision

1. A new `account.py` market suite runs `test_account_read[market, method]` over the
   reference market cases, one event loop per account and market. It never asserts
   account contents: empty orders, fills, payments and zero balances pass. It checks:
   1. `fees`: four finite rates, non-negative taker rates, magnitudes below 1.
   2. `open_orders`: `OrderState` items with non-empty IDs, finite non-negative
      prices, non-zero quantities, and filled quantities of the same sign and no
      larger magnitude.
   3. `trades_history`: a 30-day window, at most two pages; timezone-aware times
      inside the window, positive prices, non-zero quantities, boolean `maker`, fees
      absent or finite with a non-empty asset, equal to `rules().fee_asset` whenever
      that is a string (ADRs 0028 and 0039).
   4. `funding_payments` (perpetuals): finite amounts at aware times in the window.
   5. `position`: finite size, non-negative on spot. `perp_position`: a non-negative
      entry price, positive while the size is non-zero, and the same size as
      `position()`.
   6. `collateral`: finite values, free collateral not above equity, non-negative
      on spot. `perp_collateral`: also non-negative margins, maintenance not above
      initial, non-negative leverage and a `cross` or `isolated` mode.
   7. `leverage`: finite and positive. `available_notional`: finite and
      non-negative, with no equality to collateral, since venue caps may lower it
      (ADR 0041).
   8. `query_order` is statically excluded as `order_lifecycle`: a real order ID
      requires trading. `trades_stream` stays in the Bitget suite.
2. Account `fees()` moves from the public suite to this one for every venue; the
   Hyperliquid-only public fee read and its `private_account_fees` exclusion go away.
3. The verifier rebuilds each account case's exclusion offline, in this order:
   `order_lifecycle`; `perp_only` (perpetual reads on spot); `unsupported` (not in
   the `impl.toml` methods, or listed for that exchange); `credential_mode` (the
   recorded account mode cannot serve the method); `bitget_classic` (perpetual
   `collateral`/`perp_collateral` on a Classic account). A declared, unexcluded read
   raising `NotImplementedError` or `AuthError` is a failure.
4. Each `impl.toml` with account reads declares `[qualification.market]`:
   `min_mode` (`address`, `token` or `private`), `address_methods`,
   `token_methods`, and an optional `[qualification.market.unsupported]` table of
   exchange ID to methods. Every other account read needs private credentials. The
   table is qualification policy, not support: the support matrix ignores it.
   At landing: `private` for Aster, Binance, Bit2Me, Bitget, Bybit, Coinbase, Kraken
   and MEXC; `address` for dYdX and Hyperliquid; `token` for Lighter. Deribit and
   KuCoin declare no account reads, so all their account cases are `unsupported`.
5. Qualification keeps one mainnet account per venue slug. The worker derives the
   account mode from the resolved account, the credentials the client actually
   receives (an API key outranks a Lighter token, as in `typed-lighter`), and records
   `account_mode`. The verifier rejects modes below `min_mode`. Missing credentials
   lower the mode or skip the case visibly; neither qualifies (CONTRIBUTING rule 3).
   The tracked Aster account becomes signed (`public = false`) and Lighter's uses a
   read-only `auth_token`. A test checks every tracked release account meets
   `min_mode` from its declared fields, without reading `.env`.
6. One report remains: `sdk-dev test surfaces` records these cases with the market
   suite. Read evidence moves to payload version 5 with `account_mode`; version-4
   reports are rejected, never relabelled (ADR 0034).
7. Evidence stores only the case ID, network, counts, exclusion code and account
   mode. Account checks fail with fixed messages (`pytest.fail(..., pytrace=False)`)
   so balances, identifiers and raw errors never appear in output or evidence.
8. Waivers cover declared reads the single qualification account cannot observe.
   `[[qualification.market.waived]]` entries name an `exchange`, a `method`, a
   `reason` from a closed set and a non-empty `note`. The verifier rebuilds them as
   `waived:<reason>` exclusions. It rejects duplicates and waivers naming an unknown
   reference exchange, a non-account method or a read that is already excluded. A
   waived read still runs. Only its reason's expected error becomes a visible skip:
   `credential_scope` takes `AuthError` and `account_setting` takes
   `NotImplementedError`. Any other failure or malformed value still fails. If the read
   works, it passes and is recorded as passed: the simplest honest outcome, which
   shows that the waiver may be stale. A waived row must be exactly one pass or one
   skip, never a failure. The evidence summary lists every waived case and its outcome.
   The initial waivers are:
   1. Binance `usdm` `fees`, `credential_scope`: the qualification key has no USD-M
      Futures permission, and it cannot be granted from the maintainer's region.
   2. MEXC `spot` `fees`, `account_setting`: the account has MX deduction enabled,
      for which personal spot fees are declared unsupported. The setting is not
      changed for qualification.
9. Hyperliquid's perpetual `collateral`/`perp_collateral` support unified accounts
   only and raise `ApiError` on default-mode accounts. This is documented in
   impl.toml, not waived. The qualification address must be in unified mode.
10. The Bitget suite keeps its public reads, private streams and mode-specific
   rejections; its generic account-read tests are removed as duplicates.

## Alternatives considered

1. A separate `accounts` report scope: one more required directory and fingerprint
   per venue, for cases that share the market suite's fixtures and reference markets.
2. A secondary per-venue account, e.g. a private Hyperliquid key beside the address:
   more secrets in qualification for reads the weaker mode already serves.
3. Mode tables in `sdk-dev`: a second hand-maintained venue list that would drift
   from the `impl.toml` declarations it qualifies.
4. Missing credentials as exclusions: would let an unconfigured environment record
   passing evidence without any account observation.

## Consequences

1. Live qualification changes, so every venue in scope needs fresh read evidence
   (ADR 0033). Releases now observe account reads, which may expose adapter or
   account-configuration failures that previously went unseen; those must be fixed
   or explicitly decided, not excluded ad hoc.
2. Evidence attests one account in one mode, not every account type: for example a
   Bitget UTA run, a Hyperliquid unified account or MEXC with MX deduction are only
   covered when the qualification account is in that state.
3. Waived reads are unverified by release evidence. Binance USD-M account fees and
   MEXC spot fees with MX deduction disabled remain unobserved until a key or account
   can serve them. Release notes must carry the summary's waiver list. A waiver is
   removed once its read passes. It never covers other failures of the same read.
4. `available_notional()` is now attested for non-negativity only (amends ADR 0041's
   last consequence); its caps are not compared with collateral.
5. Acceptance is not release readiness; recorded evidence remains separate.
