# ADR 0033: Change-scoped venue release evidence

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; amends [ADR 0003](0003-local-consistency-release-evidence.md),
   [ADR 0013](0013-all-read-suites-release-gate.md), and
   [ADR 0032](0032-sdk-gateway.md).
2. Date: 2026-10-05

Amended by [ADR 0034](0034-offline-evidence-maintenance.md): verifier-only changes
and this schema migration require offline checks, not fresh live qualification.
Already-published adapter releases may advance each venue’s baseline.

## Context

The SDK now ships a gateway alongside its interfaces. Requiring fresh live venue
observations for gateway transport or command changes couples independent behavior
and discourages keeping the gateway beside the contracts it serves. Evidence must
still detect changes to the code, tests and dependencies it actually qualifies.

## Decision

1. Both release PR checks and publication compute affected venues from the complete
   candidate delta against the highest prior package version tag reachable from
   the candidate (`sdk-v*` or `<venue>-v*`). Tags are the repository's publication
   baseline. Full history and tags are required; a missing baseline requires all
   venues in that release's scope. A release PR's base commit is not a baseline:
   relevant edits already merged to main must still qualify. Publication repeats
   the calculation on the exact merged candidate.
2. A venue implementation's source, tests, integration tests and support declaration
   affect that venue. Shared SDK source/tests, qualification tooling/tests,
   registry, Python/test configuration and runtime requirements affect all venues
   in scope. Unknown files inside those source/test trees remain relevant.
3. Exclude only `tribulnation/sdk/gateway/` and `packages/sdk/test/gateway/` from
   venue qualification. Gateway protocol, codec, proxy, lifetime, CLI and installed
   packaging remain covered by offline regression/build checks. Shared types and
   runtime behavior used by adapters are never exempt just because the gateway
   also uses them. Documentation remains outside venue fingerprints.
4. Normalize candidate package versions and descriptive package metadata. Exclude
   the SDK's `gateway` optional dependencies and `tribulnation.commands` gateway
   entry point, and normalize the root editable SDK requirement with `[gateway]`.
   Core dependencies, build configuration and other extras/entry points remain
   relevant. Apply these boundaries to both source and actual installed-package
   hashes. Installed candidate version, import origin and checkout provenance
   still must match the current checkout. External dependency identities and
   executable contents remain exact; internal normalized versions use `0`.
5. Require existing read-suite/consistency coverage and seven-day freshness only
   for affected venues. With no affected venues, do not read reports, Catalogue
   snapshots or recorded dependency pins. This explicitly permits gateway-only
   and version-only releases without fresh live venue evidence. For affected
   venues, missing, stale, mismatched or failed evidence still blocks release.
   Only affected venues contribute installation constraints.
6. Fingerprint and manifest schema version 2 marks the changed boundary. Old
   reports are rejected, never relabeled or rehashed. This policy migration itself
   changes qualification tooling and requires fresh evidence. The first gateway
   release also adds a core CLI dependency and does not qualify for an exemption.

## Alternatives considered

1. Workflow path filters alone: publication could disagree, prior main changes
   could be missed, and full installed-package hashes would still drift.
2. Excluding all metadata or dependencies: would miss runtime changes.
3. Keeping unconditional all-venue qualification: unrelated gateway changes would
   continue forcing live observations without increasing gateway coverage.

## Consequences

A single shared scope module controls release impact and candidate source selection.
Offline tests cover release history, venue isolation, gateway/version exclusions,
installed metadata drift and no-evidence releases. Git history decides which
reports are required; content fingerprints still decide whether they qualify.
This is not automatic proof of gateway correctness or approval to publish.
