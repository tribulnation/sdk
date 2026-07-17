from typing_extensions import (
  AsyncIterable, AsyncIterator, Awaitable,
  Generic, Literal, TypeVar, Callable
)
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
import asyncio

from .exc import NetworkError

T = TypeVar('T')
U = TypeVar('U')

OverflowPolicy = Literal['fail', 'latest']
"""What a `StreamInbox` does when it can't keep up with its producer.

- `fail`: the inbox is failed loudly (a `NetworkError` is raised on its
  iterator) and closed, so the consumer can reconnect/recover. Buffered items
  are still delivered first -- overflow never silently discards data.
- `latest`: bounded to the newest `queue_size` items; the oldest queued item is
  dropped to make room for the newest. Intended for state streams (order book /
  depth / ticker) where an old snapshot is worthless once a newer one exists --
  use `queue_size=1` and each new item simply replaces the stale one.
"""

@dataclass
class _Closed:
  """Sentinel marking a clean end of stream (`StreamInbox.close`)."""

@dataclass
class _Failed:
  """Sentinel marking an errored end of stream (`StreamInbox.fail`)."""
  exc: Exception

@dataclass
class StreamInbox(Generic[T]):
  """A bounded, closeable async inbox: push items in, iterate them out.

  ```python
  inbox.push(item)   # feed data (subject to the overflow policy)
  inbox.close()      # clean end -> the async-for stops
  inbox.fail(exc)    # error end -> the async-for raises exc
  async for item in inbox:
    ...
  ```

  The physical queue holds one slot *more* than `queue_size`. That extra slot
  is reserved exclusively for the terminal marker (`_Closed`/`_Failed`): data
  delivery treats the queue as full at `queue_size`, so a terminal marker can
  always be delivered promptly, even when the data buffer is full. Ending the
  stream therefore never has to drop buffered data to make room (which would
  violate the "no silent drops" guarantee of the `fail` policy).
  """
  queue: asyncio.Queue['T | _Failed | _Closed']
  queue_size: int
  overflow: OverflowPolicy
  _closed: bool = field(init=False, default=False)
  _end: '_Closed | _Failed | None' = field(init=False, default=None)

  @classmethod
  def new(cls, queue_size: int = 1000, overflow: OverflowPolicy = 'fail') -> 'StreamInbox[T]':
    if queue_size < 1:
      raise ValueError('queue_size must be >= 1')
    # +1 slot reserved for the terminal marker (see class docstring).
    return cls(asyncio.Queue(maxsize=queue_size + 1), queue_size, overflow)

  @property
  def closed(self) -> bool:
    """Whether the inbox has been closed or failed (no more items accepted)."""
    return self._closed

  def push(self, item: 'T') -> bool:
    """Offer a data `item`, applying the overflow policy when the buffer is full.

    Returns `False` if the inbox is closed and cannot accept the item: either it
    was already closed/failed, or a `fail`-policy inbox just overflowed (in which
    case it has been failed and will accept nothing further).
    """
    if self._closed:
      return False
    q = self.queue
    if q.qsize() < self.queue_size:
      q.put_nowait(item)
      return True
    # Data buffer full; the reserved slot is still free.
    if self.overflow == 'fail':
      self.fail(NetworkError('stream subscriber fell behind'))
      return False
    # latest: drop the oldest queued item to make room for the newest. At the
    # intended queue_size=1 this is simply "newest replaces stale".
    q.get_nowait()
    q.put_nowait(item)
    return True

  def close(self):
    """Signal a clean end of stream; the iterator stops after buffered items."""
    self._terminate(_Closed())

  def fail(self, exc: Exception):
    """Signal an errored end of stream; the iterator raises `exc` after
    delivering whatever was already buffered."""
    self._terminate(_Failed(exc))

  def _terminate(self, marker: '_Closed | _Failed'):
    if self._closed:
      return
    self._closed = True
    # The reserved slot guarantees room without dropping buffered data.
    self.queue.put_nowait(marker)

  def __aiter__(self) -> AsyncIterator['T']:
    return self

  async def __anext__(self) -> 'T':
    if self._end is None:
      item = await self.queue.get()
      if not isinstance(item, (_Closed, _Failed)):
        return item
      # Latch the terminal so re-iterating keeps raising rather than hanging on
      # a now-empty queue.
      self._end = item
    if isinstance(self._end, _Failed):
      raise self._end.exc
    raise StopAsyncIteration

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
  `StreamInbox`. It starts with the first subscriber and stops with the last,
  so no individual subscriber's cancellation can interrupt another's read.

  Each subscriber's inbox is bounded (see `StreamInbox` / `OverflowPolicy`): a
  slow or dead consumer can never accumulate unbounded depth/trade backlog.
  """
  @dataclass
  class Context(Generic[U]):
    iterator: AsyncIterator[U]
    unsubscribe: Callable[[], Awaitable]

  subscribe_stream: Callable[[], Awaitable[Context[T]]]

  lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)
  ctx: Context[T] | None = field(init=False, default=None)
  pump: 'asyncio.Task[None] | None' = field(init=False, default=None)
  subscribers: list[StreamInbox[T]] = field(init=False, default_factory=list)

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

  def _discard(self, inbox: StreamInbox[T]):
    with suppress(ValueError):
      self.subscribers.remove(inbox)

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
        for inbox in list(self.subscribers):
          if not inbox.push(item):
            # `fail` overflow: the inbox failed itself; stop delivering to it.
            self._discard(inbox)
      # Ended on its own (e.g. a dropped connection) rather than being
      # cancelled below -- report it instead of leaking a bare
      # `StopAsyncIteration` as an opaque `RuntimeError`.
      exc: Exception = NetworkError('Upstream stream ended unexpectedly')
    except asyncio.CancelledError:
      return
    except Exception as e:
      exc = e
    for inbox in list(self.subscribers):
      inbox.fail(exc)

  @asynccontextmanager
  async def subscribe(
    self,
    *,
    queue_size: int = 1000,
    overflow: OverflowPolicy = 'fail',
  ) -> AsyncIterator[AsyncIterable[T]]:
    """Subscribe to the shared upstream with a bounded delivery inbox.

    - `queue_size`: max data items buffered for this subscriber before the
      `overflow` policy kicks in.
    - `overflow`: what happens when the buffer is full (see `OverflowPolicy`).
    """
    inbox: StreamInbox[T] = StreamInbox.new(queue_size, overflow)
    self.subscribers.append(inbox)
    await self.start()

    try:
      yield inbox
    finally:
      self._discard(inbox)
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
