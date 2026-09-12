# Local SDK consistency and release evidence

[Developer documentation](README.md)

Run exchange-dependent checks locally; CI only verifies recorded evidence. These
are maintainer-recorded drift checks, not independent proof of execution.

For the qualification environment, install the portable `crcmod` build before the
candidate requirements (using that environment's Python):

```sh
CC=/bin/false python -m pip install --force-reinstall --no-cache-dir --no-binary=crcmod crcmod==1.7
```

Upstream falls back to its pure-Python implementation when its optional C extension
cannot compile. CI uses this same build recipe. This avoids comparing a locally
pure build with a CI-compiled extension; installed contents are still fingerprinted.
Run this before recording evidence, never modify dependencies during a live run.

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
a consistency report does not replace their verification. The release gate now
requires a separate recorded run of all applicable read suites as described below.

## Publication gate

Reviewed reports belong in `release-evidence/<venue>/surfaces/` and, for market
implementations, also `release-evidence/<venue>/consistency/`. Verify a candidate with:

```sh
sdk-dev results release sdk --catalogue /path/to/catalogue/data
```

1. Core SDK releases require all supported read-suite reports for every declared
   implementation. Market implementations additionally require market consistency.
   Individual implementation releases require both applicable scopes for that
   implementation. A report of the wrong scope cannot substitute for required evidence.
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

## All supported read-only suites

```sh
sdk-dev test surfaces binance --accounts sdk.test.toml --account my-binance \
  --catalogue /path/to/catalogue/data --output /path/to/new-run/surfaces
sdk-dev test consistency binance --accounts sdk.test.toml --account my-binance \
  --catalogue /path/to/catalogue/data --output /path/to/new-run/consistency
sdk-dev results verify /path/to/new-run/surfaces --catalogue /path/to/catalogue/data
sdk-dev results verify /path/to/new-run/consistency --catalogue /path/to/catalogue/data
```

This records the existing market, Wallet/Earn/Report and applicable Bitget-specific
read-only suites. Non-market implementations need only `surfaces`. Standalone
`sdk-dev test market|wallet|earn|report|bitget` remains useful for diagnostics but
does not write qualification evidence; `surfaces` is the recording wrapper.

It stores public test/market/method identities, per-case outcomes and explicit
exclusion codes, not account IDs, balances, records or error text. Missing
credentials, unexpected skips, setup/teardown failures and incomplete inventories
block qualification. Every supported market reference case must pass candles,
rules, public depth/streams, ticker and applicable perpetual reads. The declared
unsupported MEXC perpetual stream, spot-only methods and single-page retention
cases are excluded, not passed. Bitget additionally requires its existing private
read tests and mode detection, with an explicit expected `uta` account setting.
No trading or transfers are tested.
Hyperliquid and dYdX Report reads require a configured mainnet address only; a
`public = true` account with that address needs no private key or mnemonic.
An empty or incomplete history is valid: the suite checks successful reads,
returned-record bounds and provenance, not historical completeness.

One report qualifies the selected mainnet account, not all account configurations,
chains or providers. See [ADR 0013](adr/0013-all-read-suites-release-gate.md) for scope.
Read reports use payload version 3; old non-market-only reports are not reusable.

For dYdX Report checks, select an archive provider in the accounts TOML. The runner
forwards the existing SDK configuration; it does not shorten history to a pruned
node's retention. Public mainnet market checks remain independent of this selection.

```toml
[report.dydx]
archive_node = "polkachu" # or "kingnodes"
```

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
