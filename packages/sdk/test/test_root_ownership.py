"""Root routing must reuse venues and own their lazily acquired resources."""

import asyncio
from dataclasses import dataclass, field
from types import TracebackType
from typing_extensions import AsyncContextManager, Iterable

import pytest

from tribulnation.sdk import EarnSDK, MarketSDK, ReportSDK, WalletSDK
from tribulnation.sdk.impl.accounts import Bybit
from tribulnation.sdk.market import Exchange, TradingVenue


@dataclass
class Resource:
  """Track acquisition, teardown, and deliberate failures without network I/O."""

  name: str
  events: list[str]
  enter_started: asyncio.Event = field(default_factory=asyncio.Event)
  exit_started: asyncio.Event = field(default_factory=asyncio.Event)
  enter_gate: asyncio.Event | None = None
  exit_gate: asyncio.Event | None = None
  fail_enter: bool = False
  fail_exit: bool = False
  suppress: bool = False

  async def __aenter__(self):
    """Optionally pause or fail acquisition."""
    self.events.append(f'enter:{self.name}')
    self.enter_started.set()
    if self.enter_gate is not None:
      await self.enter_gate.wait()
    if self.fail_enter:
      raise RuntimeError(f'enter:{self.name}')
    return self

  async def __aexit__(
    self,
    exc_type: type[BaseException] | None,
    exc_value: BaseException | None,
    traceback: TracebackType | None,
  ):
    """Optionally pause or fail teardown."""
    self.exit_started.set()
    if self.exit_gate is not None:
      await self.exit_gate.wait()
    self.events.append(f'exit:{self.name}')
    if self.fail_exit:
      raise RuntimeError(f'exit:{self.name}')
    return self.suppress


@dataclass(frozen=True)
class Venue(TradingVenue):
  """Minimal trading venue with the same declarative ownership as real venues."""

  owned: tuple[AsyncContextManager[object], ...]

  @property
  def venue_id(self):
    """Identify this test-only venue."""
    return 'test'

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """Declare the venue's resource chain."""
    yield from self.owned

  async def exchange(self, exchange_id: str) -> Exchange:
    """The test exercises venue routing only."""
    raise NotImplementedError

  async def exchanges(self) -> list[TradingVenue.ExchangeDescription]:
    """Expose a minimal usable venue."""
    return []


Factory = tuple[list[str], list[Venue], list[Venue]]


@pytest.fixture
def factory(monkeypatch: pytest.MonkeyPatch) -> Factory:
  """Replace venue construction, leaving the real root router lifecycle intact."""
  events: list[str] = []
  created: list[Venue] = []
  queued: list[Venue] = []

  def create(self: MarketSDK, id: str):
    """Record each construction, optionally using an injected resource chain."""
    venue = queued.pop(0) if queued else Venue((Resource(id, events),))
    created.append(venue)
    return venue

  monkeypatch.setattr(MarketSDK, '_venue', create)
  return events, created, queued


async def test_root_reuses_one_venue_per_account_and_closes_in_reverse(
  factory: Factory,
):
  """Repeated and concurrent lookups reuse account-local resources."""
  events, created, _ = factory
  async with MarketSDK() as root:
    assert created == []
    first, repeated = await asyncio.gather(root.venue('one'), root.venue('one'))
    second = await root.venue('two')
    assert first is repeated
    assert first is not second
    assert events == ['enter:one', 'enter:two']
    with pytest.raises(RuntimeError, match='already active'):
      await first.__aenter__()
  assert events == ['enter:one', 'enter:two', 'exit:two', 'exit:one']
  assert root.venue_registry.cache == {}


async def test_root_instances_do_not_share_venues(factory: Factory):
  """The same account in independent roots has independent ownership."""
  async with MarketSDK() as first, MarketSDK() as second:
    assert await first.venue('one') is not await second.venue('one')


async def test_unused_accounts_are_never_constructed(factory: Factory):
  """Entering and listing a root do not initialize any venue clients."""
  _, created, _ = factory
  async with MarketSDK() as root:
    assert await root.venues()
  assert created == []


async def test_root_reentry_gets_fresh_clients(factory: Factory):
  """A closed venue is never returned when the same root is entered again."""
  root = MarketSDK()
  async with root:
    first = await root.venue('one')
  async with root:
    second = await root.venue('one')
  assert first is not second
  assert factory[0] == ['enter:one', 'exit:one', 'enter:one', 'exit:one']


async def test_unmanaged_lookup_can_be_entered_independently(factory: Factory):
  """Outside a root context the caller can explicitly own the returned venue."""
  root = MarketSDK()
  venue = await root.venue('one')
  assert factory[0] == []
  async with venue:
    assert factory[0] == ['enter:one']
  assert factory[0] == ['enter:one', 'exit:one']


async def test_unmanaged_lookups_stay_fresh_after_caller_closes_child(factory: Factory):
  """Standalone callers never receive a previously closed client's cached state."""
  root = MarketSDK()
  first = await root.venue('one')
  async with first:
    pass
  second = await root.venue('one')
  assert second is not first
  assert factory[0] == ['enter:one', 'exit:one']
  assert root.venue_registry.cache == {}


async def test_all_outside_root_constructs_fresh_caller_managed_venues(
  factory: Factory,
):
  """The existing synchronous factory collection stays independently enterable."""
  root = MarketSDK()
  first = root.all
  second = root.all
  assert list(first) == await root.venues()
  assert all(first[id] is not second[id] for id in first)
  assert len(factory[1]) == 2 * len(first)
  assert factory[0] == []
  async with next(iter(first.values())):
    pass


async def test_all_inside_root_requires_previously_acquired_venues(factory: Factory):
  """The synchronous property cannot introduce an unowned venue into the context."""
  async with MarketSDK() as root:
    with pytest.raises(RuntimeError, match=r'await sdk.venue\(id\)'):
      _ = root.all
    assert factory[1] == []
    acquired = {id: await root.venue(id) for id in await root.venues()}
    assert all(root.all[id] is venue for id, venue in acquired.items())
  assert len(factory[0]) == 2 * len(acquired)


async def test_all_preconstructed_before_entry_remains_caller_owned(factory: Factory):
  """Entering a root never takes over objects handed to independent callers."""
  root = MarketSDK()
  first = root.all
  async with root:
    for id, venue in first.items():
      assert await root.venue(id) is not venue
  assert len(factory[0]) == 2 * len(first)


async def test_root_does_not_adopt_or_close_independently_active_venue(
  factory: Factory,
):
  """An independently entered child remains untouched by a later root context."""
  root = MarketSDK()
  standalone = await root.venue('one')
  async with standalone:
    async with root:
      assert await root.venue('one') is not standalone
    assert factory[0] == ['enter:one', 'enter:one', 'exit:one']
    assert root.venue_registry.cache == {}
  assert factory[0] == ['enter:one', 'enter:one', 'exit:one', 'exit:one']


async def test_concurrent_lookup_waits_for_acquisition(factory: Factory):
  """No caller observes a partially acquired cached venue."""
  events, created, queued = factory
  resource = Resource('slow', events, enter_gate=asyncio.Event())
  queued.append(Venue((resource,)))
  async with MarketSDK() as root:
    first = asyncio.create_task(root.venue('one'))
    await resource.enter_started.wait()
    second = asyncio.create_task(root.venue('one'))
    await asyncio.sleep(0)
    assert not first.done() and not second.done()
    assert resource.enter_gate is not None
    resource.enter_gate.set()
    assert await first is await second
    assert len(created) == 1


async def test_failed_acquisition_rolls_back_and_does_not_poison_cache(
  factory: Factory,
):
  """A failed venue is not cached and the next lookup can retry cleanly."""
  events, _, queued = factory
  queued.append(
    Venue((Resource('first', events), Resource('bad', events, fail_enter=True)))
  )
  async with MarketSDK() as root:
    with pytest.raises(RuntimeError, match='enter:bad'):
      await root.venue('one')
    assert events == ['enter:first', 'enter:bad', 'exit:first']
    assert root.venue_registry.cache == {}
    await root.venue('one')
  assert events[-2:] == ['enter:one', 'exit:one']


async def test_cancelled_acquisition_rolls_back_and_allows_retry(factory: Factory):
  """Cancellation releases earlier resources instead of caching a half-live venue."""
  events, _, queued = factory
  slow = Resource('slow', events, enter_gate=asyncio.Event())
  queued.append(Venue((Resource('first', events), slow)))
  async with MarketSDK() as root:
    lookup = asyncio.create_task(root.venue('one'))
    await slow.enter_started.wait()
    lookup.cancel()
    with pytest.raises(asyncio.CancelledError):
      await lookup
    assert events == ['enter:first', 'enter:slow', 'exit:first']
    assert root.venue_registry.cache == {}
    await root.venue('one')


async def test_exit_waits_for_inflight_acquisition_and_rejects_new_lookups(
  factory: Factory,
):
  """A venue acquired during exit is still unwound by the root."""
  events, _, queued = factory
  slow = Resource('slow', events, enter_gate=asyncio.Event())
  queued.append(Venue((slow,)))
  root = await MarketSDK().__aenter__()
  lookup = asyncio.create_task(root.venue('one'))
  await slow.enter_started.wait()
  exiting = asyncio.create_task(root.__aexit__(None, None, None))
  await asyncio.sleep(0)
  with pytest.raises(RuntimeError, match='closing'):
    await root.venue('two')
  assert slow.enter_gate is not None
  slow.enter_gate.set()
  await lookup
  await exiting
  assert events == ['enter:slow', 'exit:slow']
  assert root.venue_registry.cache == {}


async def test_teardown_failure_closes_other_venues_and_clears_cache(factory: Factory):
  """One broken exit cannot prevent later exits or fresh root reentry."""
  events, _, queued = factory
  queued.extend(
    [
      Venue((Resource('first', events),)),
      Venue((Resource('bad', events, fail_exit=True),)),
    ]
  )
  root = MarketSDK()
  with pytest.raises(RuntimeError, match='exit:bad'):
    async with root:
      await root.venue('one')
      await root.venue('two')
  assert events == ['enter:first', 'enter:bad', 'exit:bad', 'exit:first']
  assert root.venue_registry.cache == {}
  async with root:
    await root.venue('one')


async def test_cancelling_exit_waits_for_cleanup_before_propagating(factory: Factory):
  """Even repeated cancellation does not detach cleanup into a background leak."""
  events, _, queued = factory
  slow = Resource('slow', events, exit_gate=asyncio.Event())
  queued.append(Venue((slow,)))
  root = await MarketSDK().__aenter__()
  await root.venue('one')
  exiting = asyncio.create_task(root.__aexit__(None, None, None))
  await slow.exit_started.wait()
  exiting.cancel()
  await asyncio.sleep(0)
  exiting.cancel()
  await asyncio.sleep(0)
  assert not exiting.done()
  assert slow.exit_gate is not None
  slow.exit_gate.set()
  with pytest.raises(asyncio.CancelledError):
    await exiting
  assert events == ['enter:slow', 'exit:slow']
  assert root.venue_registry.cache == {}
  async with root:
    await root.venue('one')


async def test_root_preserves_resource_exception_suppression(factory: Factory):
  """The dynamic ownership stack follows the existing SDK suppression contract."""
  events, _, queued = factory
  queued.append(Venue((Resource('suppress', events, suppress=True),)))
  async with MarketSDK() as root:
    await root.venue('one')
    raise ValueError('suppressed by the owned resource')
  assert events == ['enter:suppress', 'exit:suppress']


@pytest.mark.parametrize('root_type', [EarnSDK, WalletSDK, ReportSDK])
async def test_terminal_sync_factory_then_enter_child_is_unchanged(
  root_type: type[EarnSDK] | type[WalletSDK] | type[ReportSDK],
  monkeypatch: pytest.MonkeyPatch,
):
  """Terminal's single-account synchronous lookup still returns a standalone owner."""
  events: list[str] = []
  child = Venue((Resource('client', events),))

  def create(*args: object):
    """Stand in for the optional implementation's synchronous factory."""
    return child

  monkeypatch.setattr(root_type, 'bybit', create)
  root = root_type(accounts={'account': Bybit(public=True)})
  venue = root.venue('account')
  assert venue is child
  assert events == []
  async with venue:
    assert events == ['enter:client']
  assert events == ['enter:client', 'exit:client']


async def test_terminal_direct_report_factory_stays_standalone(
  monkeypatch: pytest.MonkeyPatch,
):
  """Portfolio activities call a venue factory directly on an empty ReportSDK."""
  events: list[str] = []
  child = Venue((Resource('report-client', events),))
  account = Bybit(public=True)

  def create(self: ReportSDK, config: Bybit, id: str):
    """Verify the direct account is forwarded without consulting root accounts."""
    assert config is account
    assert id == 'portfolio-account'
    assert self.accounts == {}
    return child

  monkeypatch.setattr(ReportSDK, 'bybit', create)
  report = ReportSDK(accounts={}).bybit(account, 'portfolio-account')
  async with report:
    assert events == ['enter:report-client']
  assert events == ['enter:report-client', 'exit:report-client']
