"""Tests for reads shared between concurrent callers."""

import asyncio

import pytest

from tribulnation.sdk.core import RateLimited, SharedReads


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
    asyncio.ensure_future(reads.read('k', counter.fetch, ttl=1)) for _ in range(5)
  ]
  await asyncio.sleep(0)
  counter.release.set()
  assert await asyncio.gather(*waiting) == [1] * 5
  assert counter.calls == 1


async def test_answers_are_reused_for_ttl_only(monkeypatch: pytest.MonkeyPatch):
  """An answer serves callers for `ttl` seconds from its request's start; 0 never reuses one."""
  loop = asyncio.get_running_loop()
  now = [100.0]
  monkeypatch.setattr(loop, 'time', lambda: now[0])
  reads, counter = SharedReads(), Counter()
  counter.release.set()
  assert await reads.read('k', counter.fetch, ttl=1) == 1
  now[0] = 100.9
  assert await reads.read('k', counter.fetch, ttl=1) == 1
  assert await reads.read('k', counter.fetch, ttl=0) == 2
  now[0] = 102.0
  assert await reads.read('k', counter.fetch, ttl=1) == 3
  assert await reads.read('other', counter.fetch, ttl=1) == 4


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
    reads.read('k', fail, ttl=1), reads.read('k', fail, ttl=1), return_exceptions=True
  )
  assert all(isinstance(r, RateLimited) for r in results)
  assert calls == 1
  with pytest.raises(RateLimited):
    await reads.read('k', fail, ttl=1)
  assert calls == 2


async def test_a_cancelled_caller_leaves_the_request_running():
  """Cancelling one caller neither cancels the shared request nor loses its answer."""
  reads, counter = SharedReads(), Counter()
  first = asyncio.ensure_future(reads.read('k', counter.fetch, ttl=1))
  second = asyncio.ensure_future(reads.read('k', counter.fetch, ttl=1))
  await asyncio.sleep(0)
  first.cancel()
  counter.release.set()
  assert await second == 1
  assert await reads.read('k', counter.fetch, ttl=1) == 1
  assert counter.calls == 1


async def test_forget_drops_the_answer_and_the_request_in_flight():
  """After `forget`, reads ask again; an older request in flight doesn't store its answer."""
  reads, counter = SharedReads(), Counter()
  old = asyncio.ensure_future(reads.read('k', counter.fetch, ttl=1))
  await asyncio.sleep(0)
  reads.forget('k')
  new = asyncio.ensure_future(reads.read('k', counter.fetch, ttl=1))
  await asyncio.sleep(0)
  counter.release.set()
  assert (await old, await new) == (1, 2)
  assert await reads.read('k', counter.fetch, ttl=1) == 2
