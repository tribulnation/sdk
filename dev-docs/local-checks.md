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
   It checks every non-delisted Catalogue spot/perpetual entry's exchange, kind and
   known native ID convention. Asset base/quote verification is retired from this
   suite: the Catalogue owns asset identity, and `Rules` no longer returns those fields.
   Missing markets remain `deferred` coverage findings, not release blockers.
   An empty exchange
   ID is valid; a missing exchange field is not an implicit empty ID.
5. SDK-only instruments absent from the Catalogue do not fail these checks. Adding
   Catalogue coverage, checking instrument URLs, and Terminal cross-venue outliers
   remain separate work. The runner neither fixes data nor opens issues.
6. Kraken Futures and Bitget UTA `coin` are explicitly excluded capabilities, not
   passing checks or missing-market coverage. Bitget Classic `coin-classic` remains
   in scope. See [issue #32](https://github.com/tribulnation/sdk/issues/32).
7. Payload version 3 rejects the retired asset-observation and two-sided-only policies. Fresh reports
   are required after this policy change; old reports cannot be relabeled as passing.

## Quote comparison and scope

For each discovered exchange, selected markets are a deterministic sample plus
the venue's reference cases. Compare each ticker bid/ask with depth taken just
before and after that ticker, allowing a 0.5% band around the observed depth range.
Require a bracket no longer than 15 seconds; retry three fresh brackets before
reporting persistent mismatch. Compare each available side and require all three
snapshots to agree on absent sides. A one-sided book can pass for its observed side.
Never compare a last trade to a current midprice as if they
were simultaneous observations.

Fully empty books have one narrow exception: if all three timely brackets return
the exact ticker ID and neither the ticker nor either book has a bid or ask, the
sample stays `unavailable` with code `empty_book` but does not itself block release.
No other market is required to have liquidity. Inconsistent missing sides, invalid
prices, slow brackets and request errors remain blocking. Explicit Catalogue delistings
are `excluded/delisted` quote checks, matched by venue/kind/exchange/native ID; discovery
and SDK identity checks remain required. Never infer delisting from an empty book.
See [ADR 0011](adr/0011-liquidity-independent-consistency.md).

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

1. Core SDK releases require reports for every declared implementation. Market
   implementations require their market consistency report; non-market packages
   require the supported read suites described below. A report of the wrong scope
   cannot substitute for required evidence. Do not interpret a market report as
   verification of Wallet/Earn/Report.
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

## Non-market packages

```sh
sdk-dev test surfaces ethereum --accounts sdk.test.toml --account my-ethereum \
  --catalogue /path/to/catalogue/data --output /path/to/new-run
sdk-dev results verify /path/to/new-run --catalogue /path/to/catalogue/data
```

This records the existing Wallet/Earn/Report suites for supported read methods.
It stores fixed test names and outcome counts only, not account IDs, balances,
records or error text. Missing credentials, skips, setup/teardown failures and
incomplete inventories block qualification. No trading or transfers are tested.
An empty or incomplete history is valid: the suite checks successful reads,
returned-record bounds and provenance, not historical completeness.

One report qualifies the selected mainnet account, not all account configurations,
chains or providers. See [ADR 0006](adr/0006-release-evidence-scope.md) for scope.

Deribit additionally supports the explicitly approved split qualification:

```sh
sdk-dev test surfaces deribit --accounts sdk.test.toml --account deribit_public \
  --testnet-account deribit_testnet --catalogue /path/to/catalogue/data \
  --output /path/to/new-run
```

The primary account must use `venue = "deribit"`; it may use `public = true`.
The private account must use `venue = "deribit_testnet"`. Wallet/Earn metadata is
checked on mainnet; only private Report functionality is checked on testnet.
Every result records its network. Mainnet private-account behavior remains
unverified and must be noted in the release. This exception cannot qualify market
data or other venues. See [ADR 0012](adr/0012-deribit-public-mainnet-private-testnet.md).
