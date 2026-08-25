# Lifecycle

> Every SDK object is an async context manager. Declare what you own with
> `resources()`; never write `__aenter__`.

```python
async with ReportSDK(accounts).venue('bit2me') as report:
  snapshot = await report.snapshot()
```

Entering an object enters everything it owns, in order, and exits in reverse. If
acquisition fails partway, whatever was already entered is rolled back before the
error propagates.

## Declaring resources

`SDK` implements `__aenter__`/`__aexit__` once, in terms of `resources()`. To own
something, override that:

```python
from tribulnation.sdk import SDK


@dataclass(frozen=True)
class Snapshots(SDK):
  client: VenueClient

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    yield self.client
```

`resources()` is a **data** method, and that is the whole point. Overrides
compose:

```python
class Report(_Report, Snapshots):
  def resources(self):
    yield from super().resources()  # the client, from Snapshots
    yield self.extra_stream  # plus our own
```

Overriding `__aenter__` instead would not compose. A class combining two SDK
surfaces has two `__aenter__` implementations in its MRO and exactly one wins —
silently, with no error, discarding whatever the other owned. That failure mode is
invisible in testing: calls still succeed because most clients connect lazily, and
the only symptom is a leaked socket per instance.

**Do not decorate `resources()` with `@SDK.method`.** It is a sync generator, so
the wrapper would open and close the tracing span around generator *creation*
rather than iteration — an empty span, with the body invisible to middleware.

## Entering a parent enters its children

Objects obtained from an entered parent are already live:

```python
async with venue:
  market = await venue.perp_market('BTC')
  await market.depth()  # correct -- already entered
```

Re-entering one is an error:

```python
async with venue:
  market = await venue.perp_market('BTC')
  async with market:  # RuntimeError: resources are already active
    ...
```

Enter whichever level you actually hold. Entering a child directly is fine when
you did not enter its parent.

## Sharing one client between owners

Repeats within a single `resources()` are de-duplicated by identity, so
`yield from super().resources()` is safe even when both branches name the same
client.

That does **not** extend across owners. Two independent objects that each yield
the same client will enter it twice, through two separate stacks:

```python
class Outer(SDK):
  def resources(self):
    yield Inner()  # Inner also yields `shared`
    yield shared  # entered twice
```

Share a client by having exactly one owner declare it and the others borrow it.

## Writing an owner

`SDK` imposes nothing on your class: no constructor, no fields, no metaclass.
Resource state is kept in `__dict__` rather than a dataclass field, so frozen
dataclasses, non-frozen dataclasses, and plain classes all work, and a
`__post_init__` that assigns to `self` is unaffected.

One MRO caveat: **never list `SDK` explicitly alongside a mixin that already
inherits it.**

```python
class MarketMixin(SDK, ExchangeMixin):   # TypeError once ExchangeMixin inherits SDK
class MarketMixin(ExchangeMixin):        # correct
```

That is an unsatisfiable C3 linearization and fails at import.

## Cleanup that is not a resource

When teardown does not correspond to something acquired up front — closing streams
opened lazily during the block — yield a closer rather than reaching for
`__aexit__`:

```python
@asynccontextmanager
async def closing_streams(streams: dict[str, StreamManager]):
  """Close every stream open at exit, whenever it was opened."""
  try:
    yield streams
  finally:
    await asyncio.gather(*[s.close() for s in streams.values()], return_exceptions=True)


def resources(self):
  yield self.client
  yield closing_streams(self.streams)
```

The dict is captured by reference and iterated at exit, so anything added during
the block is covered. Reverse-order exit closes the streams before the client.

## Notes

- `__aexit__` propagates a resource's suppression signal, so a resource that
  returns `True` will swallow the exception.
- Exceptions raised while *acquiring* a resource are not translated into the SDK
  error taxonomy — you may see a venue-native error from `async with`. See
  [issue #2](https://github.com/tribulnation/sdk/issues/2).
- `AsyncResources` was removed in 1.7.0. It was a second root competing with `SDK`
  for the same behaviour, which is what allowed the MRO race above. Inherit `SDK`.
