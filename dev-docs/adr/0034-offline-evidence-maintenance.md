# ADR 0034: Offline evidence maintenance does not require live qualification

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; amends [ADR 0033](0033-change-scoped-release-evidence.md).
2. Date: 2026-10-05

## Context

ADR 0033 initially classified all SDK-dev edits as live qualification changes.
That required every venue to run again just to change report fingerprinting and
release selection. It also repeated qualification for adapter changes already
published independently since the previous SDK release. Neither adds new live
observations of changed venue behavior.

## Decision

1. Changes to `sdk_dev/evidence.py`, `sdk_dev/release_scope.py` and SDK-dev's
   offline regression tests require offline verification, not live venue runs.
   In the mixed `cli/results.py` module, normalize away only the explicitly named
   offline commands and their release-scope import. Retain the AST of live runner
   functions, shared helpers, other imports and unknown future definitions.
   Changing account selection, retries, collection or live assertions remains
   qualification-relevant. Integration suites, `read_evidence.py`, consistency
   checks and coverage/exclusion policy remain relevant.
2. Apply this boundary to both source and installed SDK-dev fingerprints. Do not
   ignore the entire results module or SDK-dev package. Offline tests must prove
   that changing live collection still invalidates both fingerprint layers.
3. The SDK's `tribulnation-cli` dependency provides command discovery only. Exclude
   it, its dependency traversal and gateway-only packaging from venue evidence.
   Dependencies reached independently through venue/live-test requirements remain
   fingerprinted. Changes to shared SDK runtime requirements remain relevant.
4. For an SDK release, a venue's already-published adapter tag may advance that
   venue's qualification baseline beyond the previous SDK release. The tag must
   be reachable from the candidate, descend from the SDK baseline and have a
   version no newer than the candidate's declared adapter version. Compare every
   relevant shared and venue input since that tag. Unpublished adapter changes and
   subsequent shared SDK changes still require fresh evidence. Implementation
   releases continue to compare against their own strictly prior version tag;
   their candidate tag cannot bypass verification. Missing SDK baselines still
   require qualification of every venue.
5. Schema-2 reports are required only when behavior changes actually require live
   evidence. This verifier migration does not itself require new observations.
   Leave existing reports untouched; do not relabel, rehash or treat schema-1
   reports as schema-2 evidence. Gateway/verifier-only releases do not read them.
   The next relevant behavior change requires fresh schema-2 reports with normal
   coverage, provenance, dependency-content and seven-day freshness checks.

## Alternatives considered

1. Run all venues for every verifier migration: high operational cost without
   exercising new venue behavior.
2. Exclude SDK-dev wholesale: would miss live runner and assertion changes.
3. Rewrite existing report hashes: would misrepresent what was recorded.

## Consequences

The gateway and verifier migration can release after offline checks and review,
without fresh venue runs. This is an explicit qualification boundary, not a claim
that the gateway was live-tested or permission to merge or publish. Release PRs
and publication use the same planner, including published adapter baselines.
