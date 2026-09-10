# ADR 0006: Identity consistency without exact coverage; non-market evidence

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; translated rules retired by [ADR 0009](0009-catalogue-owned-asset-identity.md); Deribit scope amended by [ADR 0012](0012-deribit-public-mainnet-private-testnet.md)
2. Date: 2026-09-10
3. Amends: [ADR 0003](0003-local-consistency-release-evidence.md).

## Context

Exact Catalogue membership drifts independently of adapter correctness. Requiring
every Catalogue instrument to appear in current discovery conflates those checks.
Also, a market-only evidence policy cannot qualify Report/Wallet/Earn-only packages.

## Decision

1. Continue checking exchange identity, instrument kind, SDK identity round trips,
   and known native ID conventions. Compare translated rules for instruments shared
   by SDK discovery and the Catalogue. Do not normalize IDs during validation.
2. Missing Catalogue markets are explicit `deferred` / `coverage_deferred` findings,
   not passes and not release blockers. Wrong or missing exchange IDs and known
   API/web namespace mismatches remain failures. Exact coverage and URL validation
   belong to a later Catalogue pass. ID conventions do not prove market existence.
   The already-deferred Kraken Futures product is an explicit policy exclusion,
   not an unknown-exchange exception inferred from discovery failures. Its entries
   remain visible as excluded; Kraken spot still requires qualification.
3. Add `sdk-dev test surfaces` to run the existing read-only Wallet/Earn/Report
   suites on one explicitly selected mainnet account. Require every applicable
   generic check: wallet deposit/withdrawal discovery, earn instrument discovery,
   report snapshot shape and history bounds/provenance. Do not execute mutations.
4. Record only fixed test names and pass/fail/skip counts, never account identifiers,
   balances, history records, raw errors or tracebacks. Failed setup/teardown,
   missing checks, skips and worker failures block verification. The worker's
   diagnostics are captured and discarded. This remains trusted local evidence,
   not independent proof.
5. Empty and incomplete API history is acceptable. Checks validate returned records
   and successful reads, not completeness; file ingestion supplies missing history.
6. Core release requires evidence for every declared implementation. Market packages
   retain market consistency policy; packages without market support require the
   applicable surface report. The verifier rejects substituting one scope for the
   other. Market reports do not certify those packages' private account surfaces.

## Alternatives considered

1. Waive all Catalogue checks: would hide exchange and asset identity bugs.
2. Treat missing markets as passing: would conceal unresolved coverage.
3. Waive non-market evidence: would leave shipped implementations unqualified.
4. Store raw private results: unnecessary for drift checks and unsafe for public PRs.

## Consequences

Existing evidence is stale after the policy/code change. Reports retain seven-day
expiry and before/after fingerprints. A non-market report qualifies the selected
mainnet account and supported reads, not all account modes, chains, providers or
historical completeness. Broader coverage remains visible follow-up work.
Acceptance does not authorize merging or publication.
