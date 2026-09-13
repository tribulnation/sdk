# dYdX 0.7.1 qualification

This patch restores native snapshot collateral and entry prices together, fixing
[issue #39](https://github.com/tribulnation/sdk/issues/39). History continues to use
chronological average-cost fill replay. Downstream dependency rollout and repair of
persisted snapshots remain separate work.

Qualification on 2026-09-13 used Python 3.12, typed-dydx 3.1.0, SDK 2.0.0, and the
portable crcmod 1.7 build required by CI. The mainnet account configuration used
`public = true`, a maintainer-supplied address, and
`[report.dydx] archive_node = "kingnodes"`. No account address, balances, history
records, or credentials are included here. Polkachu returned HTTP 502 from its gRPC
service; its incomplete run is not release evidence.

- All 741 unit tests passed. The eight new snapshot regression cases fail on the
  unpatched implementation and pass on this candidate, covering longs, shorts,
  partial closes, multiple subaccounts, and fill/snapshot size or timing mismatch.
- dYdX type checking and lint, documentation checks, and wheel/sdist validation passed.
- `surfaces/` records the complete supported read-only suite: 20 passing checks,
  no failed/skipped checks, and one explicit not-applicable exclusion.
- `consistency/` records all 212 passing market consistency checks. Both recorded
  directories passed `sdk-dev results verify` against the release Catalogue.

The consistency CLI without retries encountered indexer HTTP 429 responses. The
passing run invoked the unchanged official recorder under the SDK's existing
bounded retry middleware, as follows (paths are placeholders):

```python
from sdk_dev.cli import app
from tribulnation.sdk import Context, NetworkError, RateLimited

with Context().retried(NetworkError, RateLimited, max_retries=5).use():
  app([
    'test', 'consistency', 'dydx',
    '--accounts', '/path/to/accounts.toml', '--account', 'dydx_release',
    '--catalogue', '/path/to/catalogue/data',
    '--output', '/path/to/new-evidence/consistency',
  ])
```

No assertions, coverage requirements, quote brackets, or request timeouts were
changed. The recorder captured before/after source and dependency fingerprints
itself; failed runs were not substituted for passing checks. Evidence expires
under the normal seven-day release policy.
