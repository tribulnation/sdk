from typing_extensions import (
  AsyncIterable, AsyncIterator, Awaitable,
  Generic, TypeVar, Callable
)
from contextlib import asynccontextmanager, suppress
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

  ```python
  async with stream_fan_out.subscribe() as stream:
    async for msg in stream:
      ...
  ```

  A dedicated pump task, owned by the `Subscription` rather than any one
  subscriber, reads the upstream once and pushes to every subscriber's
  queue. It starts with the first subscriber and stops with the last, so no
  individual subscriber's cancellation can interrupt another's read.
  """
  @dataclass
  class Context(Generic[U]):
    iterator: AsyncIterator[U]
    unsubscribe: Callable[[], Awaitable]

  subscribe_stream: Callable[[], Awaitable[Context[T]]]

  lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)
  ctx: Context[T] | None = field(init=False, default=None)
  pump: 'asyncio.Task[None] | None' = field(init=False, default=None)
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
      if self.pump is None or self.pump.done():
        self.ctx = await self.subscribe_stream()
        self.pump = asyncio.create_task(self._pump(self.ctx))

  async def _pump(self, ctx: 'Subscription.Context[T]'):
    """Read `ctx.iterator` and fan out items to every subscriber.

    Runs as its own task, independent of any subscriber's lifecycle, so a
    subscriber's cancellation can never propagate into `ctx.iterator` and
    take the shared upstream down for everyone else. `start()`/`subscribe()`
    own `ctx`/`pump` entirely (via `Task.done()`) -- this only reads and
    notifies.
    """
    try:
      async for item in ctx.iterator:
        for queue in self.subscribers:
          queue.put_nowait(item)
      # Ended on its own (e.g. a dropped connection) rather than being
      # cancelled below -- report it instead of leaking a bare
      # `StopAsyncIteration` as an opaque `RuntimeError`.
      exc: Exception = NetworkError('Upstream stream ended unexpectedly')
    except asyncio.CancelledError:
      return
    except Exception as e:
      exc = e
    for queue in self.subscribers:
      queue.put_nowait(_Failed(exc))

  @asynccontextmanager
  async def subscribe(self) -> AsyncIterator[AsyncIterable[T]]:
    queue: asyncio.Queue[T | _Failed] = asyncio.Queue()
    self.subscribers.append(queue)
    await self.start()

    async def stream() -> AsyncIterable[T]:
      while True:
        item = await queue.get()
        if isinstance(item, _Failed):
          raise item.exc
        yield item

    try:
      yield stream()
    finally:
      self.subscribers.remove(queue)
      async with self.lock:
        if self.subscribers or self.pump is None or self.ctx is None:
          return
        pump, ctx = self.pump, self.ctx
        self.pump = self.ctx = None
      pump.cancel()
      with suppress(asyncio.CancelledError):
        await pump
      with suppress(Exception):
        await ctx.unsubscribe()
