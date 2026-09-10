# ADR 0003: Local consistency checks and offline release evidence

[ADR index](README.md) · [Developer documentation](../README.md)

1. Status: accepted; amended by [ADR 0004](0004-empty-book-consistency-coverage.md), [ADR 0006](0006-release-evidence-scope.md) and [ADR 0009](0009-catalogue-owned-asset-identity.md)
2. Date: 2026-09-10

## Context

Live SDK checks may require credentials or a network location unavailable in CI.
The Catalogue and upstream APIs inevitably drift. A reviewed local result should
therefore be tied to the code, dependency contents and Catalogue it actually ran
against, without presenting a checksum as proof that the run happened.

## Decision

1. Run live SDK consistency checks locally through `sdk-dev test consistency`.
   Capture fingerprints automatically before and after the run. A separate
   `sdk-dev results verify` command validates a saved report without exchange
   credentials or live venue calls.
2. Fingerprint relevant SDK, SDK-dev and implementation code, tests and behavioral
   configuration; actual installed dependency contents and metadata; Python
   major/minor; and the explicit Catalogue snapshot. Do not fingerprint credentials
   or substitute a Git commit identifier for the executed contents.
3. Store sanitized public observations, strict structured results, timestamps,
   fingerprints and reproducible dependency pins. Reject incomplete, changed,
   mismatched or expired reports. Never overwrite an existing report directory.
4. Reconstruct required checks from current policy and discovery. Missing checks,
   unavailable observations and unexpected unsupported methods block verification.
   Only committed capability declarations permit explicit exclusions. A reported
   `pass` is not by itself sufficient evidence of coverage.
5. Gate release PR checks and the publication job on matching, passing reports;
   verify the exact merged candidate before publication. A passing report does
   not authorize merging or releasing. Core SDK releases require all declared
   market implementations; non-market package releases remain blocked until an
   applicable evidence policy exists.
6. Keep responsibilities separate: SDK internal consistency and exact Catalogue
   identity/translated rules are checked here. Catalogue URL and coverage checks,
   Terminal cross-venue price outliers, automatic issue creation and automatic
   corrections are outside this implementation.

## Initial implementation policy

1. Evidence expires after seven days. CI uses Python 3.12 and checks out the current
   Catalogue, so a Catalogue change requires a fresh compatible run.
2. Validate discovered exchange/market identities and bulk, selected and empty
   ticker/perpetual-statistic selections. Compare sampled ticker bid/ask against
   surrounding depth snapshots, with a 0.5% allowance, a 15-second bracket and up
   to three attempts. These are bounded consistency tolerances, not an atomic
   snapshot guarantee.
3. Check every non-delisted Catalogue spot/perpetual instrument for exact venue,
   exchange, market and kind, and for rules base/quote translations to the declared
   canonical assets. SDK markets absent from the Catalogue are not failures here.
4. Existing deterministic tests and read-only live suites remain complementary.
   This first consistency report does not certify personal fees, Wallet, Earn or
   Report behavior. Those capabilities must not be advertised as covered by it.

## Alternatives considered

1. Live checks entirely in CI: insufficient for local credentials and regional
   access constraints.
2. Separate manual checksum generation: could fingerprint code different from the
   code that produced the observations.
3. Treat stored results as attestations: rejected. A trusted maintainer can forge
   them; the intended guarantee is drift detection, not authenticity.

## Consequences

1. Dependency or Catalogue changes can block publication even without an SDK edit.
2. Failures remain inspectable findings, not instructions to rewrite the Catalogue.
3. Passing evidence must be reviewed and refreshed before the release train can
   proceed. This ADR records the mechanism, not release readiness.
