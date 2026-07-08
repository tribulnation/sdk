from typing_extensions import (
  AsyncIterable, AsyncIterator, Awaitable,
  Generic, TypeVar, Callable, Any
)
from dataclasses import dataclass, field
import asyncio

from .exc import NetworkError

T = TypeVar('T')
U = TypeVar('U')

async def noop():
  ...

@dataclass
class _Failed:
  """Sentinel put on subscriber queues when the upstream source dies unexpectedly."""
  exc: Exception

@dataclass
class Stream(AsyncIterable[T], Generic[T]):
  stream: AsyncIterable[T]
  unsubscribe: Callable[[], Awaitable] = noop

  def __aiter__(self):
    return self.stream.__aiter__()

  @classmethod
  def polled(cls, next: Callable[[], Awaitable[T]]) -> 'Stream[T]':
    stopped = False

    async def stream():
      nonlocal stopped
      while not stopped:
        yield await next()

    async def unsubscribe():
      nonlocal stopped
      stopped = True

    return cls(stream(), unsubscribe)



@dataclass
class Subscription(Generic[T]):
  """Fan out a stream to multiple subscribers.
  
  Subscribers usage:

  ```python
  stream = await stream_fan_out.subscribe()
  async for msg in stream:
    ...
  await stream.unsubscribe()
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
  def of(cls, subscribe: Callable[[], Awaitable[Stream[T]]]) -> 'Subscription[T]':
    async def subscribe_stream():
      stream = await subscribe()
      return cls.Context(aiter(stream.stream), stream.unsubscribe)
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

  async def subscribe(self) -> Stream[T]:
    queue = asyncio.Queue()
    self.subscribers.append(queue)
    await self.start()

    unsubscribed = asyncio.Future()

    async def stream() -> AsyncIterable[T]:
      while True:
        if queue.empty():
          await self.step()
        done, _ = await asyncio.wait([unsubscribed, asyncio.create_task(queue.get())], return_when='FIRST_COMPLETED')
        if unsubscribed in done:
          break
        else:
          item = await next(iter(done))
          if isinstance(item, _Failed):
            raise item.exc
          yield item

    async def unsubscribe():
      if unsubscribed.done():
        return
      unsubscribed.set_result(None)
      self.subscribers.remove(queue)
      async with self.lock:
        if not self.subscribers and self.ctx is not None:
          await self.ctx.unsubscribe()
          self.ctx = None
          
    return Stream(stream(), unsubscribe)