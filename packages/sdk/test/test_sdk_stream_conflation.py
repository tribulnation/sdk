"""`Subscription` conflates its upstream only while every subscriber wants the newest
item, and every stream reports the items its subscriber skipped."""

import asyncio

import pytest
from typing_extensions import AsyncIterator

from tribulnation.sdk.core import (
  OverflowPolicy,
  SkippingView,
  StreamInbox,
  Subscription,
  latest_only,
  skipped,
)


@pytest.mark.parametrize(
  ('queue_size', 'overflow', 'expected'),
  [
    (1, 'latest', True),
    (2, 'latest', False),
    (1, 'fail', False),
    (1000, 'fail', False),
  ],
)
def test_latest_only(queue_size: int, overflow: OverflowPolicy, expected: bool):
  """Only a one-slot `'latest'` inbox lets the source conflate."""
  assert latest_only(queue_size, overflow) is expected


def test_inbox_counts_latest_drops():
  """A `'latest'` inbox counts each item it replaced unread."""
  inbox = StreamInbox[int].new(1, 'latest')
  for item in range(4):
    inbox.push(item)
  assert inbox.skipped == 3
  assert skipped(inbox) == 3


def test_skipped_is_none_for_uncounted_streams():
  """Streams that do not count skips report None, not 0."""

  async def items() -> AsyncIterator[int]:
    """Yield nothing."""
    for item in list[int]():
      yield item

  assert skipped(items()) is None


class Feed:
  """A controllable upstream recording how each opening conflated."""

  def __init__(self):
    self.opened: list[bool] = []
    """Whether each opening kept only the newest item."""
    self.closed = 0
    self.items = asyncio.Queue[int]()
    self.skipped = 0

  async def open(self, *, latest: bool) -> Subscription.Context[int]:
    """Open the upstream, conflating when `latest`."""
    self.opened.append(latest)

    async def items() -> AsyncIterator[int]:
      """Yield what the test feeds."""
      while True:
        yield await self.items.get()

    async def close():
      """Count closings."""
      self.closed += 1

    return Subscription.Context(items(), close, lambda: self.skipped)

  def subscription(self) -> Subscription[int]:
    """A fan-out over this feed, conflating while allowed."""
    return Subscription(lambda: self.open(latest=False), lambda: self.open(latest=True))


async def test_latest_subscribers_open_conflated():
  """Newest-only subscribers share one conflated opening."""
  feed = Feed()
  sub = feed.subscription()
  async with sub.subscribe(queue_size=1, overflow='latest'):
    async with sub.subscribe(queue_size=1, overflow='latest'):
      pass
  assert feed.opened == [True]
  assert feed.closed == 1


async def test_capturing_subscriber_reopens_unconflated():
  """A subscriber wanting every item reopens a conflated upstream, which then stays
  unconflated while it is shared."""
  feed = Feed()
  sub = feed.subscription()
  async with sub.subscribe(queue_size=1, overflow='latest') as newest:
    async with sub.subscribe(queue_size=10, overflow='fail') as every:
      await feed.items.put(1)
      assert await anext(aiter(every)) == 1
      assert await anext(aiter(newest)) == 1
      async with sub.subscribe(queue_size=1, overflow='latest'):
        pass
  assert feed.opened == [True, False]
  assert feed.closed == 2


async def test_without_latest_opener_never_conflates():
  """A `Subscription` without `subscribe_latest` always opens the full upstream."""
  feed = Feed()
  sub = Subscription(lambda: feed.open(latest=False))
  async with sub.subscribe(queue_size=1, overflow='latest'):
    pass
  assert feed.opened == [False]


async def test_upstream_skips_are_credited_to_subscribers():
  """Each subscriber's `skipped` adds the upstream's skips while it was subscribed to
  its own inbox drops."""
  feed = Feed()
  sub = feed.subscription()
  async with sub.subscribe(queue_size=1, overflow='latest') as stream:
    feed.skipped = 5
    await feed.items.put(1)
    assert await anext(aiter(stream)) == 1
    assert stream.skipped == 5
    view = SkippingView(stream, stream)
    assert skipped(view) == 5


async def test_failed_reopen_fails_the_other_subscribers():
  """If the unconflated reopening fails, subscribers of the closed upstream see it."""
  feed = Feed()
  opened = 0

  async def open_full() -> Subscription.Context[int]:
    """Fail to open."""
    nonlocal opened
    opened += 1
    raise ConnectionError('refused')

  sub = Subscription(open_full, lambda: feed.open(latest=True))
  async with sub.subscribe(queue_size=1, overflow='latest') as newest:
    with pytest.raises(ConnectionError):
      async with sub.subscribe(queue_size=10, overflow='fail'):
        pass
    with pytest.raises(ConnectionError):
      await anext(aiter(newest))
  assert opened == 1
  assert sub.subscribers == []
