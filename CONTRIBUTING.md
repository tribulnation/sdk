# Contributing

## Repository layout

```
docs/                 # user-facing docs; docs/contract/*.yml feeds the generated method reference
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
- Docs: `sdk-dev docs check` (`--fix` rewrites the generated GitHub-only blocks; CI runs
  the check on every push); `just docs-refresh` renders them into a local landing checkout

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

Release the SDK before the impls: their `tribulnation-sdk` floors require the new version
to exist on PyPI. Raise those floors in the same release as any change to a base class
impls subclass — an impl resolved against an older SDK fails silently rather than at
import.
