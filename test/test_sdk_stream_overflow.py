"""Unit + integration tests for bounded subscriber queues and overflow policies.

Covers the per-subscriber delivery policies (`fail` / `latest` / `drop_oldest`)
and the reserved-terminal-slot invariant that guarantees a stream's end/error is
always delivered promptly without silently dropping buffered data.
"""

import asyncio

import pytest

from tribulnation.sdk.core import NetworkError, Subscription
from tribulnation.sdk.core.stream import StreamInbox, _Failed, _Closed


def drain(queue: asyncio.Queue):
  out = []
  while not queue.empty():
    out.append(queue.get_nowait())
  return out


async def collect(inbox):
  out = []
  async for item in inbox:
    out.append(item)
  return out


# --- StreamInbox unit tests (synchronous push, deterministic) ---------------

def test_queue_size_must_be_positive():
  with pytest.raises(ValueError):
    StreamInbox.new(0, 'fail')


def test_fail_overflow_queues_failed_and_keeps_buffer():
  inbox = StreamInbox.new(2, 'fail')
  assert inbox.push('a') is True
  assert inbox.push('b') is True
  # Data buffer full -> next item overflows: inbox is failed and closed.
  assert inbox.push('c') is False
  assert inbox.closed is True

  items = drain(inbox.queue)
  assert items[:2] == ['a', 'b']  # buffered data is preserved, not dropped
  assert isinstance(items[2], _Failed)
  assert isinstance(items[2].exc, NetworkError)


def test_latest_overflow_keeps_only_newest():
  inbox = StreamInbox.new(1, 'latest')
  assert inbox.push('a') is True
  assert inbox.push('b') is True  # replaces the stale 'a'
  assert inbox.push('c') is True  # replaces the stale 'b'
  assert drain(inbox.queue) == ['c']


def test_latest_keeps_rolling_window_of_newest():
  inbox = StreamInbox.new(3, 'latest')
  for x in 'abc':
    assert inbox.push(x) is True
  assert inbox.push('d') is True  # drops the oldest ('a') to fit the newest
  assert drain(inbox.queue) == ['b', 'c', 'd']


def test_terminal_delivered_into_reserved_slot_when_buffer_full():
  # A full data buffer must not block the terminal marker, and must not force
  # any buffered item to be dropped to make room.
  inbox = StreamInbox.new(2, 'fail')
  assert inbox.push('a') is True
  assert inbox.push('b') is True
  assert inbox.queue.qsize() == 2  # data buffer full; reserved slot still free

  inbox.fail(NetworkError('ended'))
  items = drain(inbox.queue)
  assert items[:2] == ['a', 'b']
  assert isinstance(items[2], _Failed)


def test_terminal_is_idempotent_and_never_overflows_queue():
  inbox = StreamInbox.new(1, 'fail')
  inbox.push('a')
  inbox.fail(NetworkError('x'))
  inbox.fail(NetworkError('y'))  # already closed -> no-op, no raise
  inbox.close()                  # ditto
  items = drain(inbox.queue)
  assert items[0] == 'a'
  assert isinstance(items[1], _Failed)
  assert len(items) == 2  # only one terminal marker


def test_push_after_close_is_rejected():
  inbox = StreamInbox.new(4, 'latest')
  inbox.push('a')
  inbox.close()
  assert inbox.push('b') is False
  items = drain(inbox.queue)
  assert items[0] == 'a'
  assert isinstance(items[1], _Closed)
  assert len(items) == 2


# --- StreamInbox iteration (the reusable async-iterable interface) ----------

async def test_close_ends_iteration_cleanly():
  inbox: StreamInbox[str] = StreamInbox.new(4, 'latest')
  inbox.push('a')
  inbox.push('b')
  inbox.close()
  assert await collect(inbox) == ['a', 'b']  # clean stop, no exception


async def test_fail_raises_after_buffered_items():
  inbox: StreamInbox[str] = StreamInbox.new(4, 'latest')
  inbox.push('a')
  inbox.fail(NetworkError('boom'))
  seen = []
  with pytest.raises(NetworkError):
    async for item in inbox:
      seen.append(item)
  assert seen == ['a']  # buffered item delivered before the error


async def test_iteration_latches_terminal_and_does_not_hang():
  inbox: StreamInbox[str] = StreamInbox.new(4, 'latest')
  inbox.close()
  assert await asyncio.wait_for(collect(inbox), timeout=2) == []
  # Re-iterating a closed inbox keeps raising StopAsyncIteration, never hangs.
  assert await asyncio.wait_for(collect(inbox), timeout=2) == []


# --- Subscription integration tests -----------------------------------------

def driven_subscription():
  """A `Subscription` whose upstream is fed manually via the returned queue.

  Push items to drive the pump; push `None` to end the upstream.
  """
  upstream: asyncio.Queue = asyncio.Queue()

  async def subscribe_stream():
    async def gen():
      while True:
        item = await upstream.get()
        if item is None:
          return
        yield item
    async def unsubscribe():
      ...
    return Subscription.Context(gen(), unsubscribe)

  return Subscription(subscribe_stream), upstream


async def _settle():
  for _ in range(20):
    await asyncio.sleep(0)


async def test_fail_subscriber_gets_buffer_then_networkerror():
  sub, upstream = driven_subscription()
  cm = sub.subscribe(queue_size=2, overflow='fail')
  stream = await cm.__aenter__()

  for x in ('a', 'b', 'c'):  # third item overflows the size-2 buffer
    upstream.put_nowait(x)
  await _settle()

  items = []
  with pytest.raises(NetworkError):
    async for it in stream:
      items.append(it)
  assert items == ['a', 'b']  # loud failure, but buffered data delivered first

  await cm.__aexit__(None, None, None)


async def test_latest_subscriber_skips_stale_and_sees_newest():
  sub, upstream = driven_subscription()
  cm = sub.subscribe(queue_size=1, overflow='latest')
  stream = await cm.__aenter__()

  for x in ('a', 'b', 'c'):
    upstream.put_nowait(x)
  await _settle()

  first = await asyncio.wait_for(stream.__aiter__().__anext__(), timeout=2)
  assert first == 'c'  # stale 'a'/'b' skipped, newest book delivered

  await cm.__aexit__(None, None, None)
