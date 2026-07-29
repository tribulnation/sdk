"""Tests for declarative async resource lifecycles."""

from dataclasses import dataclass

import pytest

from tribulnation.sdk import SDK
from tribulnation.sdk.reporting import Report, Snapshots


@dataclass
class Resource:
  name: str
  events: list[str]
  fail: bool = False

  async def __aenter__(self):
    self.events.append(f'enter:{self.name}')
    if self.fail:
      raise RuntimeError(self.name)
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    self.events.append(f'exit:{self.name}')


@dataclass(frozen=True)
class Owner(SDK):
  resources_to_enter: tuple[Resource, ...]
  def resources(self):
    yield from self.resources_to_enter


async def test_async_resources_enter_and_exit_in_order():
  events: list[str] = []
  owner = Owner((Resource('one', events), Resource('two', events)))

  async with owner:
    assert events == ['enter:one', 'enter:two']

  assert events == [
    'enter:one', 'enter:two', 'exit:two', 'exit:one',
  ]


async def test_async_resources_roll_back_partial_entry():
  events: list[str] = []
  owner = Owner((
    Resource('one', events),
    Resource('two', events, fail=True),
  ))

  with pytest.raises(RuntimeError, match='two'):
    await owner.__aenter__()

  assert events == ['enter:one', 'enter:two', 'exit:one']


async def test_async_resources_reject_reentry_and_exit_before_entry():
  events: list[str] = []
  owner = Owner((Resource('one', events),))

  with pytest.raises(RuntimeError, match='not active'):
    await owner.__aexit__(None, None, None)

  await owner.__aenter__()
  with pytest.raises(RuntimeError, match='already active'):
    await owner.__aenter__()
  await owner.__aexit__(None, None, None)


# --- SDK-provided lifecycle -------------------------------------------------


async def test_bare_sdk_subclass_is_a_no_op_context_manager():
  """`SDK` alone is enterable and owns nothing."""
  class Bare(SDK):
    ...

  async with Bare() as bare:
    assert isinstance(bare, Bare)


async def test_sdk_subclass_enters_its_declared_resources():
  events: list[str] = []

  @dataclass
  class Owns(SDK):
    resource: Resource
    def resources(self):
      yield self.resource

  async with Owns(Resource('one', events)):
    assert events == ['enter:one']
  assert events == ['enter:one', 'exit:one']


async def test_report_subclassing_a_concrete_snapshots_still_enters_it():
  """A concrete `Snapshots` mixed into `Report` must keep its lifecycle.

  `Report` is `Report(History, Snapshots)`. When those bases each defined a no-op
  `__aenter__`, one of them won the MRO and the concrete implementation's resources were
  silently never entered -- a leaked socket per instance, with correct results otherwise.
  This is the shape of that bug; it must stay fixed.
  """
  events: list[str] = []

  @dataclass
  class VenueSnapshots(Snapshots):
    resource: Resource
    def resources(self):
      yield self.resource
    async def snapshot(self, assets=None):
      raise NotImplementedError

  @dataclass
  class VenueReport(Report, VenueSnapshots):
    def history(self, start=None, end=None):
      raise NotImplementedError

  async with VenueReport(Resource('client', events)):
    assert events == ['enter:client'], 'concrete Snapshots resources were skipped'
  assert events == ['enter:client', 'exit:client']


async def test_resources_compose_through_super():
  """`yield from super().resources()` merges both branches of a diamond."""
  events: list[str] = []

  @dataclass
  class Base(SDK):
    first: Resource
    def resources(self):
      yield self.first

  @dataclass
  class Derived(Base):
    second: Resource
    def resources(self):
      yield from super().resources()
      yield self.second

  async with Derived(Resource('one', events), Resource('two', events)):
    pass
  assert events == ['enter:one', 'enter:two', 'exit:two', 'exit:one']


async def test_repeated_resources_are_entered_once():
  """Composition legitimately yields a shared client twice; it must enter once."""
  events: list[str] = []
  shared = Resource('shared', events)

  @dataclass
  class Owns(SDK):
    def resources(self):
      yield shared
      yield shared

  async with Owns():
    pass
  assert events == ['enter:shared', 'exit:shared']


async def test_dedup_does_not_span_separate_owners():
  """De-duplication covers one owner's `resources()`, not resources nested inside others.

  `yield from super().resources()` is one iteration, so composition is safe. But two
  independent owners that each yield the same client enter it twice, through two stacks.
  Share a client by having exactly one owner declare it and the others borrow it.
  """
  events: list[str] = []
  shared = Resource('shared', events)

  @dataclass
  class Inner(SDK):
    def resources(self):
      yield shared

  @dataclass
  class Outer(SDK):
    def resources(self):
      yield Inner()
      yield shared

  async with Outer():
    pass
  assert events == ['enter:shared', 'enter:shared', 'exit:shared', 'exit:shared']


async def test_frozen_dataclass_sdk_subclass_owns_state():
  """State lives in `__dict__`, so frozen subclasses need no field.

  Guards against anyone making the lifecycle carry a dataclass field again: that would
  make frozen-ness contagious and is a `TypeError` against non-frozen venue mixins.
  """
  events: list[str] = []

  @dataclass(frozen=True)
  class Frozen(SDK):
    resource: Resource
    def resources(self):
      yield self.resource

  async with Frozen(Resource('one', events)):
    pass
  assert events == ['enter:one', 'exit:one']


async def test_non_frozen_dataclass_with_post_init_owns_state():
  """The bitget shape: a non-frozen dataclass building sub-objects in `__post_init__`."""
  events: list[str] = []

  @dataclass
  class Mutable(SDK):
    resource: Resource
    def __post_init__(self):
      self.derived = f'derived:{self.resource.name}'
    def resources(self):
      yield self.resource

  owner = Mutable(Resource('one', events))
  assert owner.derived == 'derived:one'
  async with owner:
    pass
  assert events == ['enter:one', 'exit:one']


async def test_exit_can_suppress_an_exception():
  """`AsyncExitStack` propagates a resource's suppression signal. Now uniform."""
  class Suppressing:
    async def __aenter__(self):
      return self
    async def __aexit__(self, exc_type, exc_value, traceback):
      return True

  class Owns(SDK):
    def resources(self):
      yield Suppressing()

  async with Owns():
    raise RuntimeError('swallowed')
