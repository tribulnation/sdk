"""Tests for reads shared between concurrent callers."""

import asyncio
from datetime import timedelta

import pytest

from tribulnation.sdk.core import RateLimited, SharedReads

SECOND = timedelta(seconds=1)


class Counter:
  """A fetch that counts its calls and waits for `release` before answering."""

  def __init__(self):
    self.calls = 0
    self.release = asyncio.Event()

  async def fetch(self) -> int:
    """Answer the call number once released."""
    self.calls += 1
    call = self.calls
    await self.release.wait()
    return call


async def test_concurrent_callers_share_one_request():
  """Callers arriving while a request is in flight await its answer."""
  reads, counter = SharedReads(), Counter()
  waiting = [
    asyncio.ensure_future(reads.read('k', counter.fetch, ttl=SECOND)) for _ in range(5)
  ]
  await asyncio.sleep(0)
  counter.release.set()
  assert await asyncio.gather(*waiting) == [1] * 5
  assert counter.calls == 1


async def test_answers_are_reused_for_ttl_only(monkeypatch: pytest.MonkeyPatch):
  """An answer serves callers for `ttl` from its request's start; `timedelta(0)` never reuses one."""
  loop = asyncio.get_running_loop()
  now = [100.0]
  monkeypatch.setattr(loop, 'time', lambda: now[0])
  reads, counter = SharedReads(), Counter()
  counter.release.set()
  assert await reads.read('k', counter.fetch, ttl=SECOND) == 1
  now[0] = 100.9
  assert await reads.read('k', counter.fetch, ttl=SECOND) == 1
  assert await reads.read('k', counter.fetch, ttl=timedelta(0)) == 2
  now[0] = 102.0
  assert await reads.read('k', counter.fetch, ttl=SECOND) == 3
  assert await reads.read('other', counter.fetch, ttl=SECOND) == 4


async def test_failures_are_shared_but_not_kept():
  """Every caller of a failed request sees its error; the next read asks again."""
  reads, calls = SharedReads(), 0

  async def fail() -> int:
    """Fail after a yield, so concurrent callers join the request."""
    nonlocal calls
    calls += 1
    await asyncio.sleep(0)
    raise RateLimited('limited')

  results = await asyncio.gather(
    reads.read('k', fail, ttl=SECOND),
    reads.read('k', fail, ttl=SECOND),
    return_exceptions=True,
  )
  assert all(isinstance(r, RateLimited) for r in results)
  assert calls == 1
  with pytest.raises(RateLimited):
    await reads.read('k', fail, ttl=SECOND)
  assert calls == 2


async def test_a_cancelled_caller_leaves_the_request_running():
  """Cancelling one caller neither cancels the shared request nor loses its answer."""
  reads, counter = SharedReads(), Counter()
  first = asyncio.ensure_future(reads.read('k', counter.fetch, ttl=SECOND))
  second = asyncio.ensure_future(reads.read('k', counter.fetch, ttl=SECOND))
  await asyncio.sleep(0)
  first.cancel()
  counter.release.set()
  assert await second == 1
  assert await reads.read('k', counter.fetch, ttl=SECOND) == 1
  assert counter.calls == 1


async def test_forget_drops_the_answer_and_the_request_in_flight():
  """After `forget`, reads ask again; an older request in flight doesn't store its answer."""
  reads, counter = SharedReads(), Counter()
  old = asyncio.ensure_future(reads.read('k', counter.fetch, ttl=SECOND))
  await asyncio.sleep(0)
  reads.forget('k')
  new = asyncio.ensure_future(reads.read('k', counter.fetch, ttl=SECOND))
  await asyncio.sleep(0)
  counter.release.set()
  assert (await old, await new) == (1, 2)
  assert await reads.read('k', counter.fetch, ttl=SECOND) == 2


async def test_fresh_reads_neither_reuse_nor_join(monkeypatch: pytest.MonkeyPatch):
  """`ttl=None` starts its own request even while an answer is stored or one is in flight."""
  loop = asyncio.get_running_loop()
  monkeypatch.setattr(loop, 'time', lambda: 100.0)
  reads, counter = SharedReads(), Counter()
  counter.release.set()
  assert await reads.read('k', counter.fetch, ttl=SECOND) == 1
  assert await reads.read('k', counter.fetch, ttl=None) == 2
  counter.release.clear()
  shared = asyncio.ensure_future(reads.read('k', counter.fetch, ttl=timedelta(0)))
  await asyncio.sleep(0)
  fresh = asyncio.ensure_future(reads.read('k', counter.fetch, ttl=None))
  await asyncio.sleep(0)
  counter.release.set()
  assert (await shared, await fresh) == (3, 4)
  assert counter.calls == 4


async def test_a_fresh_answer_serves_later_sharing_callers():
  """Sharing callers join a fresh read's request and reuse its stored answer."""
  reads, counter = SharedReads(), Counter()
  fresh = asyncio.ensure_future(reads.read('k', counter.fetch, ttl=None))
  await asyncio.sleep(0)
  joined = asyncio.ensure_future(reads.read('k', counter.fetch, ttl=timedelta(0)))
  await asyncio.sleep(0)
  counter.release.set()
  assert (await fresh, await joined) == (1, 1)
  assert await reads.read('k', counter.fetch, ttl=SECOND) == 1
  assert counter.calls == 1


async def test_only_the_latest_request_stores_its_answer():
  """A request superseded by a fresh read answers its callers but stores nothing."""
  reads = SharedReads()
  gates = [asyncio.Event(), asyncio.Event()]
  calls = 0

  async def fetch() -> int:
    """Answer the call number once that call's gate opens."""
    nonlocal calls
    calls += 1
    call = calls
    await gates[call - 1].wait()
    return call

  old = asyncio.ensure_future(reads.read('k', fetch, ttl=SECOND))
  await asyncio.sleep(0)
  new = asyncio.ensure_future(reads.read('k', fetch, ttl=None))
  await asyncio.sleep(0)
  gates[1].set()
  assert await new == 2
  gates[0].set()
  assert await old == 1
  assert await reads.read('k', fetch, ttl=SECOND) == 2
  assert calls == 2


async def test_callers_judge_one_answer_by_their_own_ttl(
  monkeypatch: pytest.MonkeyPatch,
):
  """One stored answer serves a lenient caller while a stricter one asks again."""
  loop = asyncio.get_running_loop()
  now = [100.0]
  monkeypatch.setattr(loop, 'time', lambda: now[0])
  reads, counter = SharedReads(), Counter()
  counter.release.set()
  assert await reads.read('k', counter.fetch, ttl=SECOND) == 1
  now[0] = 102.0
  assert await reads.read('k', counter.fetch, ttl=timedelta(seconds=5)) == 1
  assert await reads.read('k', counter.fetch, ttl=SECOND) == 2
  assert await reads.read('k', counter.fetch, ttl=timedelta(seconds=5)) == 2
  assert counter.calls == 2


async def test_forget_drops_a_fresh_request_too():
  """A fresh request in flight during `forget` answers its caller but stores nothing."""
  reads, counter = SharedReads(), Counter()
  fresh = asyncio.ensure_future(reads.read('k', counter.fetch, ttl=None))
  await asyncio.sleep(0)
  reads.forget('k')
  counter.release.set()
  assert await fresh == 1
  assert await reads.read('k', counter.fetch, ttl=SECOND) == 2
