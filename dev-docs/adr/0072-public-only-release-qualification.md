# ADR 0072: Public-only release qualification

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; implemented, not release-verified; amends
   [ADR 0042](0042-read-only-account-method-qualification.md)
2. Date: 2026-11-19

## Context

ADR 0042 makes release evidence observe every declared account read on one
qualification account, at the venue's `min_mode` (`address`, `token` or `private`).
That account's credentials sit in the maintainer's environment and its reads run on
every qualification. For EVEDEX the maintainer has decided that no private-data tests
run at all: no API key is used for release evidence. Its account reads and Report
were verified by hand on mainnet on 2026-11-19. Under ADR 0042 the venue cannot
qualify without a key: a public account is below any minimum, and a Report needing an
API key fails on it.

## Decision

1. `[qualification.market] min_mode` also accepts `public`. It is an opt-in per venue
   and requires a non-empty `note` in the same table giving the reason; loading an
   `impl.toml` with `public` and no note fails.
2. On such a venue, a declared account read the recorded mode cannot serve is the
   exclusion `public_only`, in place of `credential_mode`. The verifier rebuilds it
   offline like every other code (ADR 0042 decision 3, same position in the order).
   Like any non-waiver exclusion, the case does not run and must record no outcome.
3. Report on such a venue, when it needs authentication (`auth = true`) and the
   recorded account is public, is the same `public_only` exclusion for each of its
   checks, rather than a failure.
4. A stronger account on such a venue still runs every read its mode serves: the
   exclusions follow the recorded mode, not the declaration alone.
5. The evidence summary states plainly that the venue's account reads and Report are
   NOT verified by release evidence, with the count of each, and `sdk-dev test surfaces`
   and `sdk-dev results verify` print the same statement. A `public_only` code is never
   a pass.
6. Every other venue is unchanged: its mode ordering, `credential_mode` code and
   below-minimum rejection apply as before, so a public account is still rejected on a
   venue whose minimum is `address` or higher.
7. EVEDEX declares `min_mode = "public"` (no private-data tests by policy; account
   reads and Report verified by hand on mainnet on 2026-11-19, not by release
   evidence). Its tracked `evedex` account becomes `public = true` with no key;
   `evedex_trade` keeps its keys for hand-run checks and is not used for qualification.
   `token_methods` stays, recording what an API key serves.

## Alternatives considered

1. Waivers (ADR 0042 decision 8): a waived read still runs and needs the account to
   reach it; their reasons cover one read the account cannot observe, not a policy of
   no private data.
2. Declaring the account reads and Report unsupported: would misstate the support
   matrix, which they serve.
3. Keeping `credential_mode` for these cases: the code reads as an under-configured
   account, while this is a declared, reviewed policy that the summary must name.

## Consequences

1. EVEDEX releases attest public market reads and consistency only. Its account reads
   (`fees`, orders, fills, positions, collateral, leverage, notional and position
   limits) and Report snapshots can regress without release evidence noticing; they
   rely on hand verification and unit tests, and release notes should say so.
2. The change touches live qualification inputs (`sdk-dev` sources), so every venue in
   scope of the next release needs fresh evidence (ADR 0033). The shared SDK has
   already changed since 4.2.0, so this adds no venue to the 4.2.1 scope. Payload
   version 5 is unchanged: no field is added, and existing reports of other venues
   rebuild the same inventory.
3. Opting another venue in is a reviewed `impl.toml` change with its own reason.
4. Acceptance is not release readiness; recorded evidence remains separate.
