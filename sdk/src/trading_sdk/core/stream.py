from typing_extensions import (
  AsyncIterable, AsyncIterator, Awaitable,
  Generic, TypeVar, Callable, Any
)
from dataclasses import dataclass, field
import asyncio

T = TypeVar('T')
U = TypeVar('U')

async def noop():
  ...

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
  subscribers: list[asyncio.Queue[T]] = field(init=False, default_factory=list)

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
      T = await anext(self.ctx.iterator)
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
          yield await next(iter(done))

    async def unsubscribe():
      unsubscribed.set_result(None)
      self.subscribers.remove(queue)
      if not self.subscribers and self.ctx is not None:
        async with self.lock:
          await self.ctx.unsubscribe()
          self.ctx = None
          
    return Stream(stream(), unsubscribe)