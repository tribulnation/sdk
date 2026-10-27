"""Utilities for owning groups of asynchronous tasks and sharing reads between callers."""

from collections.abc import AsyncGenerator, Awaitable, Callable, Hashable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import asyncio
from typing_extensions import Any, TypeVar, cast

T = TypeVar('T')


@asynccontextmanager
async def managed_tasks(
  awaitables: Iterable[Awaitable[T]],
) -> AsyncGenerator[tuple[asyncio.Future[T], ...]]:
  """Own tasks and drain every task when leaving the context."""
  tasks = tuple(asyncio.ensure_future(awaitable) for awaitable in awaitables)
  try:
    yield tasks
  finally:
    for task in tasks:
      if not task.done():
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@dataclass
class SharedReads:
  """Reads that concurrent callers share, each answer reused for a short while.

  One request per key is in flight at a time: callers arriving meanwhile await the same
  answer (single-flight). A successful answer is then reused for `ttl` seconds counted
  from when its request started, so it is never older than `ttl` plus that request's
  own latency. Failures are not kept: the next caller asks again. A caller's
  cancellation never cancels the shared request, which still stores its answer.

  Meant for one client's account-wide reads (positions, balances, bulk snapshots) that
  many markets or tasks read back to back; never share one between accounts.
  """

  answers: dict[Hashable, tuple[float, Any]] = field(
    default_factory=dict[Hashable, tuple[float, Any]]
  )
  """Each key's last answer, with the loop time its request started."""
  inflight: dict[Hashable, asyncio.Future[Any]] = field(
    default_factory=dict[Hashable, asyncio.Future[Any]]
  )
  """Each key's request in flight."""

  async def read(
    self, key: Hashable, fetch: Callable[[], Awaitable[T]], *, ttl: float
  ) -> T:
    """`fetch()`'s answer for `key`, shared with concurrent callers and reused for `ttl` seconds.

    Args:
      key: What is read; callers reading the same thing must use equal keys.
      fetch: The request, called only when no fresh answer or request in flight exists.
      ttl: Seconds an answer stays reusable; 0 never reuses a stored answer, but still
        joins a request already in flight.
    """
    loop = asyncio.get_running_loop()
    now = loop.time()
    answer = self.answers.get(key)
    if answer is not None and now - answer[0] < ttl:
      return cast(T, answer[1])
    future = self.inflight.get(key)
    if future is None or future.get_loop() is not loop:
      future = asyncio.ensure_future(self.request(key, fetch, started=now))
      future.add_done_callback(retrieve)
      self.inflight[key] = future
    return cast(T, await asyncio.shield(future))

  def forget(self, key: Hashable):
    """Drop what is known of `key`, e.g. after a write that changes it: the next read asks again.

    A request already in flight still answers its own callers, but neither stores its
    answer nor serves later ones, since it may predate the write.
    """
    self.answers.pop(key, None)
    self.inflight.pop(key, None)

  async def request(
    self, key: Hashable, fetch: Callable[[], Awaitable[T]], *, started: float
  ) -> T:
    """Run `fetch()` for `key`, storing its answer unless `forget` dropped the request meanwhile."""
    try:
      value = await fetch()
      if self.inflight.get(key) is asyncio.current_task():
        self.answers[key] = (started, value)
      return value
    finally:
      if self.inflight.get(key) is asyncio.current_task():
        del self.inflight[key]


def retrieve(future: asyncio.Future[Any]):
  """Mark a shared request's failure as seen, so one nobody awaited any more isn't reported as never retrieved."""
  if not future.cancelled():
    future.exception()
