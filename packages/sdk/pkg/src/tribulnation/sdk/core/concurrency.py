"""Utilities for owning groups of asynchronous tasks and sharing reads between callers."""

from collections.abc import AsyncGenerator, Awaitable, Callable, Hashable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
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
  """Reads that concurrent callers share, each answer reused as long as its caller allows.

  Each read states its `ttl`, how old an answer it accepts (ADR 0054):

  - A `timedelta` (`timedelta(0)` included) shares: an answer whose request started less
    than `ttl` ago is returned as is; otherwise the caller joins a request already in
    flight (single-flight), or starts one.
  - `None` asks afresh: it always starts a request, after the call, and neither returns
    a stored answer nor joins a request in flight, which may predate something the
    caller just saw (e.g. its own fill). Its answer is still stored and, while it is in
    flight, joined by later sharing callers.

  An answer is never older than its `ttl` plus its request's own latency. Callers with
  different `ttl`s share one key: each read judges the stored answer by its own. Only
  the latest request started for a key stores its answer, so a stored answer never
  goes back in time. Failures are not kept: the next caller asks again. A caller's
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
  """Each key's latest request in flight."""

  async def read(
    self, key: Hashable, fetch: Callable[[], Awaitable[T]], *, ttl: timedelta | None
  ) -> T:
    """`fetch()`'s answer for `key`, no older than `ttl` allows.

    Args:
      key: What is read; callers reading the same thing must use equal keys.
      fetch: The request, called only when no stored answer or request in flight serves
        the read.
      ttl: How long ago the request of a reusable answer may have started; `timedelta(0)`
        reuses none, but joins a request in flight. `None` neither reuses nor joins:
        it always starts a request.
    """
    loop = asyncio.get_running_loop()
    now = loop.time()
    future = None
    if ttl is not None:
      answer = self.answers.get(key)
      if answer is not None and now - answer[0] < ttl.total_seconds():
        return cast(T, answer[1])
      inflight = self.inflight.get(key)
      if inflight is not None and inflight.get_loop() is loop:
        future = inflight
    if future is None:
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
    """Run `fetch()` for `key`, storing its answer if it is still the key's latest request.

    A request stops being the latest when `forget` drops it or a fresh read (`ttl=None`)
    starts another.
    """
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
