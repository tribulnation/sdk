# Local SDK consistency and release evidence

[Developer documentation](README.md)

Run exchange-dependent checks locally; CI only verifies recorded evidence. These
are maintainer-recorded drift checks, not independent proof of execution.

## Run and verify

```sh
sdk-dev test consistency binance \
  --catalogue /path/to/catalogue/data \
  --accounts sdk.test.toml \
  --output /path/to/new-run

sdk-dev results verify /path/to/new-run \
  --catalogue /path/to/catalogue/data
```

1. Omit `--accounts` to use public defaults. With multiple matching configured
   accounts, select one explicitly with `--account`. Only mainnet matches count
   toward this release policy; testnet observations cannot attest mainnet behavior.
2. The output must be a new directory: recording never silently replaces old
   evidence. Fingerprints are captured before and after the checks automatically.
   Code or dependency changes during a run prevent a valid attestation.
3. Missing credentials, request errors, unavailable required observations, missing
   checks, stale fingerprints, and failed comparisons block verification. A declared
   unsupported method is a visible exclusion, not a successful observation.
4. The initial suite checks exact exchange/market identities, bulk and selected
   ticker/perpetual-stat keys, empty selections, and sampled ticker/depth quotes.
   It checks every non-delisted Catalogue spot/perpetual entry for the venue against
   the exact exchange and market and translated rules base/quote. An empty exchange
   ID is valid; a missing exchange field is not an implicit empty ID.
5. SDK-only instruments absent from the Catalogue do not fail these checks. Adding
   Catalogue coverage, checking instrument URLs, and Terminal cross-venue outliers
   remain separate work. The runner neither fixes data nor opens issues.

## Quote comparison and scope

For each discovered exchange, selected markets are a deterministic sample plus
the venue's reference cases. Compare each ticker bid/ask with depth taken just
before and after that ticker, allowing a 0.5% band around the observed depth range.
Require a bracket no longer than 15 seconds; retry three fresh brackets before
reporting persistent mismatch. Missing book sides or ticker quotes are unavailable,
not matching prices. Never compare a last trade to a current midprice as if they
were simultaneous observations.

This suite does not call personal `fees()`, place orders, transfer funds, or claim
every discovery-only instrument received a depth comparison. The report preserves
its inventory so that sample coverage is inspectable. Existing `sdk-dev test
market|earn|wallet|report` suites and adapter regression tests remain complementary;
a consistency report does not replace their verification.

## Publication gate

Reviewed reports belong in `release-evidence/<venue>/`. Verify a candidate with:

```sh
sdk-dev results release sdk --catalogue /path/to/catalogue/data
```

1. Core SDK releases require reports for every declared market implementation;
   a market implementation release requires its own report. Packages without a
   defined consistency evidence policy fail closed until a suitable policy is
   added. Do not interpret a market report as verification of Wallet/Earn/Report.
2. Reports expire after seven days and must match current relevant SDK, adapter,
   test, support and dependency inputs, plus the Catalogue data. Git commit identity
   alone is insufficient. Reports and generated documentation are not source inputs.
3. Verification also checks the installed code, so a matching checkout cannot
   attest a run that imported a different editable installation. Reproduce the
   recorded dependency versions with each report's `dependency-pins.txt`; actual
   content fingerprints still govern. Conflicting report pins require reconciled
   runs, not resolver overrides. Evidence CI uses Python 3.12, matching local runs.
4. Release PRs check evidence against their candidate and the current Catalogue
   checkout. Publication verifies it again against the exact merged commit, not
   whatever newer commit happens to be on `main`. CI makes no exchange API calls
   and receives no exchange credentials.
5. A passing report is necessary, not release approval. Merge and publication
   still require explicit approval and the other release checks.
