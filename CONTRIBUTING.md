# Contributing

## Repository layout

```
docs/                 # user-facing docs; docs/contract/*.yml feeds the generated method reference
dev-docs/             # maintainer guides and ADRs; outside the user-docs navigation
packages/
├── sdk/
│   ├── pkg/          # tribulnation-sdk
│   ├── test/         # unit and regression tests
│   ├── README.md
│   └── LICENSE
├── sdk-dev/          # internal sdk-dev CLI
└── impl/             # exchange-specific implementations
    └── <venue>/
        ├── pkg/      # tribulnation-<venue>
        ├── test/     # unit tests
        ├── impl.toml # which surfaces this venue supports
        ├── README.md
        └── LICENSE
registry.toml         # public venue registry (display name, icon, PyPI, tier)
```

## Commands

- Format and lint: `just format`, `just check` (ruff, reads `ruff.toml`)
- Type checking: `pyright` (reads `pyrightconfig.json`)
- Unit tests: `pytest`
- Integration tests, against live APIs: `sdk-dev test earn|wallet|etc.` (credentials from `sdk.test.toml`)
- Support matrix: `sdk-dev support`
- PoC scripts (`poc/*.py`, notebooks in jupytext's percent format): `sdk-dev poc scaffold
  <venue> <surface>` writes the skeleton; `sdk-dev poc surface <venue> [--grep regex]`
  lists the typed client's endpoints; `sdk-dev poc check [venue...]` type-checks and
  lints them; `sdk-dev poc run <script> --cells 1,3,7-9` executes chosen cells into the
  paired `.ipynb` beside the script, which is gitignored because cells print live account
  data. The rules are in `.agents/skills/sdk-poc/`
- Catalogue coverage: `sdk-dev catalogue check` verifies the catalogue's translation keys
  follow each `impl.toml`'s `[ids]` form; `sdk-dev catalogue coverage [surface...]` runs the
  live surfaces and lists the IDs the catalogue cannot translate yet
- Docs: `sdk-dev docs check` (`--fix` rewrites the generated GitHub-only blocks; CI runs
  the check on every push); `just docs-refresh` renders them into a local landing checkout

## Architecture decisions

Developer guides and decision history live in [dev-docs/](dev-docs/README.md),
separate from the SDK user reference in `docs/`. Keep user-facing contracts and
examples self-contained there; SDK-dev workflows and release policy belong here
or in `dev-docs/`.

Keep load-bearing decisions in the [ADR index](dev-docs/adr/README.md): public
contracts, architecture, guarantees, policy, and meaningful tradeoffs. Read the
relevant records before changing those areas, and include a new ADR with a PR that
introduces or changes such a decision. Routine fixes do not need an ADR.

Use the numbered template and index there. Distinguish an accepted design from an
implemented or release-verified one. Once accepted, preserve the decision and its
rationale; a changed decision gets a new record that supersedes or amends the old
one, with links and status updates in both the record and index.

## Live conformance checks

For the fingerprinted local consistency suite and offline release verifier, see
[Local SDK checks](dev-docs/local-checks.md). Run `sdk-dev test consistency`
to capture both results and fingerprints; do not generate checksums as an
independent attestation step. The existing suites below remain complementary.

1. Run `sdk-dev test market|earn|wallet|report [venue-or-account] --accounts sdk.test.toml`.
   The optional selector matches an exact venue slug or account id, including aliases
   that do not contain the venue name. Without it, every eligible configured account
   (and available public default) is selected. Support comes from `impl.toml`.
2. These suites do not place/cancel orders, transfer funds, or subscribe/redeem Earn
   positions. Market checks cover reference-market discovery, books and public streams,
   rules, tickers, funding data, and candles. Rules do not fetch personal fee tiers;
   Coinbase's authenticated catalogue paths still skip on public-only accounts.
   Configure a private account to verify those reads. Account-specific Bitget checks remain
   read-only. Earn enumerates instruments; Wallet enumerates methods; Report reads a
   snapshot and the last 30 days. Binance and MEXC discover their own spot markets;
   their per-symbol history sweeps can require many requests.
3. Missing configured credential environment variables and declared unsupported methods
   are visible skips, not verification. Rejected credentials, unexpected
   `NotImplementedError`, malformed responses and transport failures remain failures.
   An all-skipped run is not evidence of release readiness.
4. Candle windows roll with time and check timezone awareness, half-open bounds,
   uniqueness, alignment and value types. They impose no response ordering or synthetic
   rows for empty venue intervals. Exact page-boundary completeness is covered by
   deterministic unit fixtures; live cross-page checks apply only where retention
   allows them. Hyperliquid's retained history fits one response, so its cross-page
   test explicitly skips.
5. Each suite uses one session event loop and owned async contexts. Error summaries
   omit raw exception payloads, which can contain credentials or account records.

## Writing SDK objects

`SDK` implements `__aenter__`/`__aexit__` once, in terms of `resources()`. Entering an
object enters everything it owns, in order, and exits in reverse; if acquisition fails
partway, whatever was already entered is rolled back before the error propagates. To own
something, override `resources()`:

```python
from tribulnation.sdk import SDK


@dataclass(frozen=True)
class Snapshots(SDK):
  client: VenueClient

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield self.client
```

It is a **data** method, and that is the whole point — overrides compose:

```python
class Report(_Report, Snapshots):
  def resources(self):
    yield from super().resources()  # the client, from Snapshots
    yield self.extra_stream  # plus our own
```

Overriding `__aenter__` instead would not. A class combining two SDK surfaces has two
`__aenter__` implementations in its MRO and exactly one wins — silently, discarding
whatever the other owned. That failure mode is invisible in testing: calls still succeed
because clients connect lazily, and the only symptom is a leaked socket per instance.

**Do not decorate `resources()` with `@SDK.method`.** It is a sync generator, so the
wrapper would open and close the tracing span around generator *creation* rather than
iteration — an empty span, with the body invisible to middleware.

**Sharing a client.** Repeats within one `resources()` are de-duplicated by identity, so
`yield from super().resources()` is safe when both branches name the same client. That
does not extend across owners: two objects that each yield the same client enter it twice,
through two separate stacks. Have exactly one owner declare it and the others borrow it.

**MRO caveat.** Never list `SDK` explicitly alongside a mixin that already inherits it —
`class MarketMixin(SDK, ExchangeMixin)` is an unsatisfiable C3 linearization and fails at
import. Inherit the mixin alone.

**Cleanup that is not a resource.** When teardown doesn't correspond to something acquired
up front — closing streams opened lazily during the block — yield a closer rather than
reaching for `__aexit__`:

```python
def resources(self):
  yield self.client
  yield closing_streams(self.streams)  # an @asynccontextmanager closing whatever is open at exit
```

The dict is captured by reference and iterated at exit, so anything added during the block
is covered. Reverse-order exit closes the streams before the client.

Two notes: `__aexit__` propagates a resource's suppression signal, so one returning `True`
swallows the exception; and `AsyncResources` was removed in 1.7.0 — it was a second root
competing with `SDK`, which is what allowed the MRO race above.

## Adding a venue

Copy the shape of an existing `packages/impl/<venue>/`: a `pkg/` package named
`tribulnation-<venue>`, `test/`, a `README.md` and `LICENSE`. Then declare it in two
places: `impl.toml` says what the package actually supports (`[support.<surface>]` with
`support`, `auth`, optional `methods` and `note`), and the root `registry.toml` lists the
venue for the site. Both feed the published support matrix — nothing there is inferred
from the code.

## Releasing

Bump `version` in the package's `pkg/pyproject.toml` on a branch named `release/sdk` or
`release/<venue>`, and open a PR touching that package. Merging it tags the commit and
publishes to PyPI (`.github/workflows/release.yml`).

Publication additionally requires matching, passing local consistency reports in
`release-evidence/<venue>/`; missing evidence blocks both release PR verification
and publication. The publication job checks the exact merged commit. Passing
evidence does not constitute approval to merge or publish.

Release the SDK before the impls: their `tribulnation-sdk` floors require the new version
to exist on PyPI. Raise those floors in the same release as any change to a base class
impls subclass — an impl resolved against an older SDK fails silently rather than at
import.
