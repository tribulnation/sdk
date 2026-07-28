"""Unit tests for `Subscription` upstream-failure and unsubscribe handling.

Regression tests for the `StopAsyncIteration` -> `RuntimeError` leak and the
non-idempotent `unsubscribe()` described in `sdk_stop_iteration_bug.md`.
"""

import asyncio

import pytest

from tribulnation.sdk.core import NetworkError, Subscription


def make_ctx_factory(items: list[object], *, on_unsubscribe=None):
  """Build a `subscribe_stream` callable whose upstream yields `items` then ends."""
  async def subscribe_stream():
    async def gen():
      for item in items:
        yield item
    async def unsubscribe():
      if on_unsubscribe is not None:
        on_unsubscribe()
    return Subscription.Context(gen(), unsubscribe)
  return subscribe_stream


async def collect(stream):
  items = []
  async for item in stream:
    items.append(item)
  return items


async def test_upstream_exhaustion_raises_network_error_not_stop_async_iteration():
  """Consuming a stream whose upstream ends must not leak a raw StopAsyncIteration/RuntimeError."""
  sub = Subscription(make_ctx_factory([1, 2]))
  cm = sub.subscribe()
  stream = await cm.__aenter__()

  items = []
  with pytest.raises(NetworkError):
    async for item in stream:
      items.append(item)
  assert items == [1, 2]

  # Cleanup must be safe even though the upstream already ended internally.
  await cm.__aexit__(None, None, None)


async def test_multiple_subscribers_all_unblocked_on_upstream_end():
  """If the shared upstream ends, every subscriber must see it, none should hang."""
  sub = Subscription(make_ctx_factory([1, 2]))
  stream_a = await sub.subscribe().__aenter__()
  stream_b = await sub.subscribe().__aenter__()

  async def collect_expecting_failure(stream):
    items = []
    with pytest.raises(NetworkError):
      async for item in stream:
        items.append(item)
    return items

  (items_a, items_b) = await asyncio.wait_for(
    asyncio.gather(collect_expecting_failure(stream_a), collect_expecting_failure(stream_b)),
    timeout=2,
  )
  assert items_a == [1, 2]
  assert items_b == [1, 2]

  assert sub.ctx is None


async def test_unsubscribe_is_idempotent_and_calls_upstream_unsubscribe_once():
  unsubscribe_calls = 0
  def on_unsubscribe():
    nonlocal unsubscribe_calls
    unsubscribe_calls += 1

  sub = Subscription(make_ctx_factory([1, 2, 3], on_unsubscribe=on_unsubscribe))
  cm = sub.subscribe()
  stream = await cm.__aenter__()
  async for _ in stream:
    break

  await cm.__aexit__(None, None, None)
  await cm.__aexit__(None, None, None)  # must not raise

  assert unsubscribe_calls == 1


async def test_unsubscribe_after_upstream_end_does_not_raise():
  """Cleanup after an upstream failure must not try to unsubscribe an already-dead context."""
  sub = Subscription(make_ctx_factory([1]))
  cm = sub.subscribe()
  stream = await cm.__aenter__()

  with pytest.raises(NetworkError):
    async for _ in stream:
      pass

  await cm.__aexit__(None, None, None)
  await cm.__aexit__(None, None, None)


async def test_unsubscribe_racing_with_upstream_failure_unsubscribes_exactly_once():
  """A departing subscriber racing the pump's own teardown must not double-unsubscribe.

  Both the pump (when the upstream dies) and `subscribe()`'s teardown (when the
  last subscriber leaves) can release `ctx`. Whichever wins, the upstream must
  see exactly one `unsubscribe()` and `ctx` must end up cleared.
  """
  upstream_may_end = asyncio.Event()
  unsub_calls = 0

  async def subscribe_stream():
    async def gen():
      yield 1
      await upstream_may_end.wait()
      # generator returns here -> StopAsyncIteration on the next anext()
    async def unsub():
      nonlocal unsub_calls
      unsub_calls += 1
    return Subscription.Context(gen(), unsub)

  sub = Subscription(subscribe_stream)
  cm = sub.subscribe()
  stream = await cm.__aenter__()

  first = await stream.__aiter__().__anext__()
  assert first == 1

  # The upstream dies at the same time as the only subscriber walks away, so
  # the pump's release path and the teardown path run concurrently.
  unsub_task = asyncio.create_task(cm.__aexit__(None, None, None))
  await asyncio.sleep(0)
  upstream_may_end.set()

  await asyncio.wait_for(unsub_task, timeout=2)

  assert unsub_calls == 1
  assert sub.ctx is None
  assert sub.pump is None


async def test_ctx_survives_teardown_by_departing_subscriber_while_another_remains():
  """A departing subscriber must not tear down the ctx another subscriber still uses."""
  upstream_may_continue = asyncio.Event()
  unsub_calls = 0

  async def subscribe_stream():
    async def gen():
      yield 1
      await upstream_may_continue.wait()
      yield 2

    async def unsub():
      nonlocal unsub_calls
      unsub_calls += 1

    return Subscription.Context(gen(), unsub)

  sub = Subscription(subscribe_stream)
  cm_a = sub.subscribe()
  stream_a = await cm_a.__aenter__()
  assert (await stream_a.__aiter__().__anext__()) == 1

  # B joins the shared upstream that A established.
  cm_b = sub.subscribe()
  stream_b = await cm_b.__aenter__()

  # A departs. It is *a* subscriber leaving, not the last one, so the shared
  # upstream must stay up for B.
  await asyncio.wait_for(cm_a.__aexit__(None, None, None), timeout=2)

  assert unsub_calls == 0, 'must not tear down the upstream ctx while B is still subscribed'
  assert sub.ctx is not None

  upstream_may_continue.set()
  assert (await asyncio.wait_for(stream_b.__aiter__().__anext__(), timeout=2)) == 2

  # B is the last one out, so now the upstream is released -- exactly once.
  await asyncio.wait_for(cm_b.__aexit__(None, None, None), timeout=2)
  assert unsub_calls == 1
  assert sub.ctx is None


async def test_upstream_failure_releases_registry_so_resubscribe_does_not_collide():
  """Regression for the dYdX 'Channel ... already subscribed' bug: an upstream
  that dies unexpectedly must release its channel registration, not just its
  own `ctx`, so a later `subscribe_stream()` call doesn't collide with a
  registry entry nothing else would ever clean up.
  """
  channel = 'v4_parent_subaccounts:owner/0'
  registry: set[str] = set()

  def make_subscribe_stream(items: list[object]):
    async def subscribe_stream():
      if channel in registry:
        raise ValueError(f'Channel {channel} already subscribed')
      registry.add(channel)

      async def gen():
        for item in items:
          yield item

      async def unsubscribe():
        registry.discard(channel)

      return Subscription.Context(gen(), unsubscribe)
    return subscribe_stream

  sub = Subscription(make_subscribe_stream([1, 2]))

  # First consumer (e.g. "hedger"): upstream ends unexpectedly mid-stream.
  stream_a = await sub.subscribe().__aenter__()
  with pytest.raises(NetworkError):
    async for _ in stream_a:
      pass

  # The failure itself, not just an explicit unsubscribe, must have released
  # the registry entry.
  assert channel not in registry

  # A later consumer (e.g. "maker" retrying) must be able to establish a
  # fresh subscription instead of hitting "already subscribed".
  stream_b = await sub.subscribe().__aenter__()
  assert (await stream_b.__aiter__().__anext__()) == 1
