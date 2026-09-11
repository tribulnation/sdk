# Local release evidence

Store reviewed, sanitized reports under `<venue>/surfaces/` for every implementation
and additionally `<venue>/consistency/` for market implementations. Generate them
locally with `sdk-dev test surfaces` and `sdk-dev test consistency`; do not
hand-author passing results. Old reports directly under `<venue>/` are retained
historical evidence only and cannot satisfy the strengthened release gate.
The runner requires a new directory, so archive or remove a superseded report
explicitly before recording its replacement. Keep failed diagnostic runs outside
this release directory until reviewed.

Each report contains fingerprints and results, a human-readable summary, and
external dependency version constraints. No accounts file, environment values,
credentials, raw private responses, or arbitrary exception messages belong here.

Release CI verifies the candidate's actual content and installed dependencies,
the current Catalogue snapshot, report freshness, and the complete required
check inventory. Reports are maintainer-recorded drift checks, not cryptographic
proof that requests ran. Review their changes like code.

No passing reports have been supplied by this README. Releases remain blocked
until the applicable evidence exists and verifies. See the
[local checking guide](../dev-docs/local-checks.md).
