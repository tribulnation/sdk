# tribulnation-sdk 2.6.1 release candidate

Python 3.10 support for account loading, and a safe Aster extra.

- `tribulnation.sdk.impl.accounts` (`load_accounts`, TOML-configured `MarketSDK`
  and other routers) imported `tomllib`, which exists only on Python 3.11+, despite
  the package's `>=3.10` floor. It now falls back to `tomli`, a new dependency
  installed only below 3.11.
- The `aster` extra requires `tribulnation-aster>=0.2.0`. Aster 0.1.0 cannot build
  its client once `typed-aster` 0.2.0 is installed, which a fresh install resolves.

No SDK interfaces change. Publication requires fresh all-venue read-suite and
applicable Market consistency evidence against the pinned Catalogue snapshot.
