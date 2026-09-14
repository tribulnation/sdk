# ADR 0016: Qualify Report snapshots in SDK releases

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted
2. Date: 2026-09-14
3. Amends ADR 0013. Preserves the Deribit network split in ADR 0012.

## Context

The Report live suite fetched a snapshot and 30 days of history for every account.
It checked that history could be read, timestamps and provenance had valid shapes,
and MEXC emitted known observation types. These checks could reveal transport or
schema errors, but did not establish historical completeness or correct accounting.
Complex reconciliation, interpretation and conservation checks belong to the
application that consumes those observations. Archive availability and expensive
history sweeps should not gate unrelated SDK releases.

## Decision

1. SDK live Report qualification calls `snapshot()` only. The fixture must not call
   `history()`, including when invoked through `sdk-dev test report` or
   `sdk-dev test surfaces`.
2. Remove the generic history fetch, timestamp, provenance and MEXC source-set tests
   from the SDK live suite. Application-level ingestion and auditing own history
   correctness checks. SDK release evidence makes no claim about history correctness
   or completeness.
3. Keep focused SDK implementation regression tests for request retries, pagination,
   parsing and lifecycle behavior. The Report history API and implementation support
   declarations are unaffected by this test-scope decision.
4. All other required live suites, market consistency, credentials, network rules,
   fingerprints and expiry checks remain required. This is a deliberate scope change,
   not an unsupported-method declaration or a successful history test.
5. Record version-4 read evidence against the updated test sources. Older reports
   cannot be relabeled or reused as new qualification; rerun the required scopes.

## Consequences

SDK release checks stop depending on complete account-history sweeps. They retain
snapshot validation and focused implementation regression coverage. History-only
transport or schema failures may instead surface during application ingestion or
targeted venue verification; SDK release success does not certify that pipeline.
