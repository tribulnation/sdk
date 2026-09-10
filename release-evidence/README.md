# Local release evidence

Store reviewed, sanitized consistency reports under `<venue>/`. Generate them
locally with `sdk-dev test consistency` (market packages) or `sdk-dev test surfaces`
(non-market packages); do not hand-author passing results.
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
