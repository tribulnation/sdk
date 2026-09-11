# ADR 0013: Require all supported read-only suites before release

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted
2. Date: 2026-09-11
3. Amends: ADRs 0003 and 0006. Preserves the Deribit network split in ADR 0012.

## Context

The previous gate selected market consistency OR non-market evidence. Consequently,
a venue with Markets could release without recorded Wallet/Earn/Report checks,
and candles, funding history, rules and streams were outside its required report.
That is insufficient for qualifying the SDK's existing read-only test surfaces.

## Decision

1. Every implementation requires `sdk-dev test surfaces` evidence for all its
   applicable existing read-only suites: market, wallet, earn, report and the
   Bitget-specific market/account and mode-detection suites. Market implementations
   additionally require `sdk-dev test consistency`. Neither report substitutes
   for the other. Core releases require these reports for every implementation.
2. Run live tests locally. Record each parameterized market/method test separately,
   reconstruct its inventory from committed suites and support, and reject missing
   or duplicated cases, missing credentials, failed setup/cleanup and unexpected
   skips. Unknown suite modules or unmapped tests fail closed.
3. Record declared unsupported reads, spot-inapplicable perp reads, MEXC's unsupported
   perp stream and reference cases with single-page retention as explicit exclusions,
   never successful tests. Existing assertions that unsupported Bitget methods raise
   are tests of rejection behavior, not evidence those methods are implemented.
4. An empty account history is valid, including MEXC's source-set check. No historical
   completeness, funded account, executed trade, order placement, cancellation,
   transfer or Earn subscription is required by this policy. Existing venue-specific
   assertions must still conform to that read-only contract.
5. Preserve mainnet qualification, except Deribit private Report tests may run on
   testnet and must retain per-result network labels. Bitget mode detection requires
   a private selected account with an explicit expected `uta` value. Evidence qualifies
   that mode/account, not every possible configuration or provider.
6. Store version-3 read evidence at `release-evidence/<venue>/surfaces/`, with market
   consistency at `release-evidence/<venue>/consistency/`. Both retain independent
   before/after source/dependency/Catalogue fingerprints and seven-day expiry.
   Include implementation-local integration suites in source fingerprints.
7. Gate release PRs and publication, not ordinary development PRs, on offline
   verification. CI receives no venue credentials. Publication rechecks the exact
   merged candidate. Passing evidence is not merge/publication approval.

## Alternatives considered

1. Run credentialed suites in CI: conflicts with local credential and venue access
   constraints.
2. Accept one aggregate pass count: can conceal omitted markets, skipped fixtures
   or missing surfaces.
3. Treat any skip as acceptable: could hide missing credentials or broken adapters.

## Consequences

Existing narrower reports cannot qualify releases. Fresh consistency and read-suite
runs are required after the implementation/test fingerprint changes. The broader
gate may expose previously untested adapter or fixture failures; fix or explicitly
resolve them before release, without silently reducing scope. This record does not
claim live qualification is complete or expand the SDK's declared capabilities.
