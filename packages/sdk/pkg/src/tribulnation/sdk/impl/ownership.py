"""Lazy, per-account resource ownership for the root SDK routers."""

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from types import TracebackType
from typing_extensions import AsyncContextManager, Callable, Generic, Iterable, TypeVar

from tribulnation.sdk.core import SDK

Venue = TypeVar('Venue', bound=SDK)


@dataclass
class VenueRegistry(Generic[Venue]):
  """Cache venues and enter them exactly once while their root is active.

  Outside a root context, lookups remain fresh caller-managed factories. Acquisition
  and teardown are serialized, so exit cannot miss an in-flight managed lookup.
  """

  cache: dict[str, Venue] = field(default_factory=dict[str, Venue])
  lock: asyncio.Lock = field(default_factory=asyncio.Lock)
  stack: AsyncExitStack | None = None
  closing: bool = False

  def unmanaged(self, id: str, create: Callable[[], Venue]) -> Venue:
    """Construct synchronously only when no root context must acquire the venue."""
    if self.closing:
      raise RuntimeError('The root SDK is closing')
    if self.lock.locked():
      raise RuntimeError('Venue acquisition is in progress; use await sdk.venue(id)')
    if id in self.cache:
      return self.cache[id]
    if self.stack is not None:
      raise RuntimeError(
        'New venues in an entered MarketSDK require await sdk.venue(id); '
        'the synchronous sdk.all property can only return already acquired venues'
      )
    venue = create()
    return venue

  async def get(self, id: str, create: Callable[[], Venue]) -> Venue:
    """Return the cached venue, acquiring a new one before exposing it to callers."""
    if self.closing:
      raise RuntimeError('The root SDK is closing')
    async with self.lock:
      if self.closing:
        raise RuntimeError('The root SDK is closing')
      if id in self.cache:
        return self.cache[id]
      venue = create()
      if self.stack is not None:
        await self.stack.enter_async_context(venue)
        self.cache[id] = venue
      return venue

  async def __aenter__(self):
    """Start owning routed lookups without constructing unused accounts."""
    if self.closing:
      raise RuntimeError('The root SDK is closing')
    async with self.lock:
      if self.stack is not None:
        raise RuntimeError('The root SDK is already active')
      self.stack = AsyncExitStack()
    return self

  async def __aexit__(
    self,
    exc_type: type[BaseException] | None,
    exc_value: BaseException | None,
    traceback: TracebackType | None,
  ) -> bool | None:
    """Close every acquired venue, then discard the cache even if cleanup fails.

    Cancellation of the exiting caller is deferred until cleanup finishes. The
    cleanup task holds the lock until all registered exits have been attempted.
    """
    self.closing = True

    async def close():
      """Wait for acquisition and unwind the owned venues in reverse order."""
      async with self.lock:
        stack, self.stack = self.stack, None
        try:
          if stack is None:
            raise RuntimeError('The root SDK is not active')
          return await stack.__aexit__(exc_type, exc_value, traceback)
        finally:
          self.cache.clear()
          self.closing = False

    task = asyncio.create_task(close())
    cancelled: asyncio.CancelledError | None = None
    while not task.done():
      try:
        await asyncio.shield(task)
      except asyncio.CancelledError as error:
        cancelled = error
    result = task.result()
    if cancelled is not None:
      raise cancelled
    return result


class VenueOwner(SDK, Generic[Venue]):
  """Compose root ownership through SDK.resources(), including frozen routers."""

  @property
  def venue_registry(self) -> VenueRegistry[Venue]:
    """Keep lifecycle state out of dataclass fields and constructor signatures."""
    registry = vars(self).get('_venue_registry')
    if registry is None:
      registry = vars(self)['_venue_registry'] = VenueRegistry[Venue]()
    return registry

  def resources(self) -> Iterable[AsyncContextManager[object]]:
    """Own the registry for this root's context, leaving all unused accounts lazy."""
    yield from super().resources()
    yield self.venue_registry
