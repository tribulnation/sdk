# ADR 0017: Venue-owned resource policies

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted
2. Date: 2026-09-17

## Context

[Issue #2](https://github.com/tribulnation/sdk/issues/2) identifies native venue
exceptions escaping SDK resource acquisition. SDK lifecycle methods also receive
context middleware: translating these errors would let retry policies replay an
entire acquisition or an already-consumed cleanup stack. Rollback of successfully
entered resources does not establish that the resource whose entry failed is reusable.

## Decision

Keep declarative `resources()` ownership and the shared ordered acquisition,
reverse cleanup, rollback, and identity de-duplication engine. Venues yield
`ManagedResource` adapters with independent entry and exit decorators, using their
existing exception translators. Adapters directly delegate lifecycle calls and
preserve suppression. They do not translate exceptions merely passed from the body.

Cache adapters for reusable clients and share the adapter when the same client is
declared repeatedly within one owner. Fresh one-shot closers use fresh adapters.
Sharing across owners still requires one owner and other borrowers.

Remove method decorators from SDK entry and exit. The active context continues to
apply to decorated calls inside lifecycle operations; whole-lifecycle middleware,
including outer logging spans and retries, no longer applies. No retry middleware
name exclusions are needed.

Initially every venue uses translation only. Venue policies may retry entry or
cleanup independently only when the underlying operation is established to be safe.
No shared layer promises that failed client entry is reusable or that cleanup can be
replayed. The failing client remains responsible for its own partial acquisition.

## Alternatives considered

- Per-venue SDK lifecycle overrides repeat orchestration and reintroduce MRO hazards.
- A translation hook on SDK couples venue policy to whole-lifecycle handling.
- Excluding lifecycle names in retry middleware retains unnecessary special cases.
- Generic lifecycle retries assume client guarantees the SDK cannot provide.

## Consequences

Callers retain `async with` syntax and receive SDK errors on translated acquisition
and cleanup failures. Context retry policies no longer replay lifecycle operations,
even when configured to catch every exception. Outer lifecycle logging spans disappear.
Venue decorators retain their existing mappings and handling of unknown exceptions.

Offline tests cover every owned-client declaration, rollback, suppression,
cancellation, identity, and decorated calls within lifecycle operations. A structural
guard prevents raw client declarations and venue SDK lifecycle overrides. This replaces
the issue's proposed SDK translation hook with resource adapters.

This record is not publication evidence. Before releasing implementations using
`ManagedResource`, publish the SDK containing it and raise implementation SDK dependency
floors to that release, following the repository release process.
