from typing_extensions import (
  AsyncIterable, AsyncIterator, Awaitable,
  Generic, TypeVar, Callable
)
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import asyncio

from .exc import NetworkError

T = TypeVar('T')
U = TypeVar('U')

@dataclass
class _Failed:
  """Sentinel put on subscriber queues when the upstream source dies unexpectedly."""
  exc: Exception

@dataclass
class Subscription(Generic[T]):
  """Fan out a stream to multiple subscribers.

  Subscribers usage:

  ```python
  async with stream_fan_out.subscribe() as stream:
    async for msg in stream:
      ...
  ```

  Internally:
  1. First subscriber triggers actual subscription to the source stream.
  2. Subsequent subscribers listen to the already-subscribed stream.
  3. When all subscribers are unsubscribed, the source stream is unsubscribed.
  """
  @dataclass
  class Context(Generic[U]):
    iterator: AsyncIterator[U]
    unsubscribe: Callable[[], Awaitable]

  subscribe_stream: Callable[[], Awaitable[Context[T]]]

  lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)
  ctx: Context[T] | None = field(init=False, default=None)
  subscribers: list[asyncio.Queue[T | _Failed]] = field(init=False, default_factory=list)

  @classmethod
  def of(
    cls, subscribe: Callable[[], Awaitable[tuple[AsyncIterable[T], Callable[[], Awaitable]]]]
  ) -> 'Subscription[T]':
    """Build a `Subscription` from a callback returning `(iterable, unsubscribe)`."""
    async def subscribe_stream():
      iterable, unsubscribe = await subscribe()
      return cls.Context(aiter(iterable), unsubscribe)
    return cls(subscribe_stream)

  async def start(self):
    async with self.lock:
      if self.ctx is None:
        self.ctx = await self.subscribe_stream()

  async def step(self):
    async with self.lock:
      if self.ctx is None:
        self.ctx = await self.subscribe_stream()
      try:
        T = await anext(self.ctx.iterator)
      except StopAsyncIteration:
        # The upstream source ended without us asking it to (e.g. a dropped
        # connection). Unblock every subscriber instead of letting the raw
        # `StopAsyncIteration` escape this async generator, which Python
        # would otherwise turn into an opaque `RuntimeError`.
        dead_ctx = self.ctx
        self.ctx = None
        try:
          # Best-effort: release the underlying channel/registry entry so a
          # later resubscribe doesn't fail against state nothing else will
          # clean up. Must not stop us from notifying subscribers below.
          await dead_ctx.unsubscribe()
        except Exception:
          ...
        failed = _Failed(NetworkError('Upstream stream ended unexpectedly'))
        for queue in self.subscribers:
          queue.put_nowait(failed)
        return
      for queue in self.subscribers:
        queue.put_nowait(T)

  @asynccontextmanager
  async def subscribe(self) -> AsyncIterator[AsyncIterable[T]]:
    queue: asyncio.Queue[T | _Failed] = asyncio.Queue()
    self.subscribers.append(queue)
    await self.start()

    async def stream() -> AsyncIterable[T]:
      while True:
        if queue.empty():
          await self.step()
        item = await queue.get()
        if isinstance(item, _Failed):
          raise item.exc
        yield item

    try:
      yield stream()
    finally:
      # Cancellation here can only land between these two statements or
      # inside `await self.ctx.unsubscribe()` -- both are fine to interrupt:
      # worst case a later subscriber's `step()` finds `self.subscribers`
      # non-empty (this one never got removed) and just keeps fanning out to
      # a queue nobody drains anymore, which is harmless.
      self.subscribers.remove(queue)
      async with self.lock:
        if not self.subscribers and self.ctx is not None:
          await self.ctx.unsubscribe()
          self.ctx = None
