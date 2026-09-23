# ADR 0026: Pin Catalogue to the qualification snapshot

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; implementation and release qualification remain separate.
2. Date: 2026-09-23
3. Amends: [ADR 0003](0003-local-consistency-release-evidence.md), specifically its moving-Catalogue release requirement.

## Context

The evidence verifier hashes every Catalogue JSON file and reconstructs Catalogue
identity, coverage and delisting checks from that input. CI previously checked out
Catalogue main, so unrelated edits invalidated completed SDK qualification with no
SDK change. Repeated live reruns chased a moving input rather than detecting an SDK
regression. Ignoring the hash while using newer data would also reconstruct a
different required inventory from the one originally observed.

## Decision

Record the full Catalogue commit SHA in release-evidence/catalogue-ref.txt. Both
release PR verification and publication check out that exact commit from the fixed
tribulnation/catalogue repository. Reject absent or non-SHA references; do not fall
back to main. The reference belongs to the checked-out SDK candidate, including
the exact merged candidate used for publication.

Continue verifying the recorded Catalogue content hash and reconstructing checks
against that snapshot. Keep all existing relevant source, tests, configuration,
installed dependency contents, Python version, report integrity, run stability,
coverage and seven-day age requirements. Changing a pin alone cannot make reports
for different data qualify. Use one clean Catalogue snapshot across each release's
required reports.

Latest-Catalogue compatibility remains a separate live consistency run, recorded
in a separate output directory. It does not change the release pin or independently
block an SDK release already qualified against its recorded snapshot.

## Consequences

Unrelated Catalogue commits no longer require fresh SDK evidence. Intentional
qualification against newer Catalogue data still requires matching observations.
The current reports can be reused because their recorded hashes already match the
pinned 1851660 snapshot; neither verifier semantics nor observed results change.
There is no report relabeling, expiry waiver, or removal of integrity checks.
