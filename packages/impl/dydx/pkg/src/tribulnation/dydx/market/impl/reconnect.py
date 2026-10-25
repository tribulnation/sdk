"""Keep the indexer's WebSocket channels open across dropped connections.

Every indexer channel of a client shares one WebSocket, so one dropped connection ends
them all. `reconnecting` reopens a channel instead, and tells its subscribers when it
dropped (`Dropped`) and when it is back (`Reconnected`): each subscriber decides whether
a gap ends it.
"""

from typing_extensions import AsyncIterator, Awaitable, Callable, TypeVar
from contextlib import suppress
from dataclasses import dataclass
import asyncio
import logging

from tribulnation.sdk.core import ApiError, NetworkError, RateLimited

log = logging.getLogger(__name__)

T = TypeVar('T')

RECONNECT_MIN = 0.5
"""First delay between reconnection attempts, in seconds."""
RECONNECT_MAX = 8.0
"""Cap of the exponential reconnection backoff, in seconds."""
GIVE_UP_AFTER = 60.0
"""Seconds a channel may stay down, reconnecting, before its subscribers get the error."""


def transient(e: Exception) -> bool:
  """Whether a reconnection retries `e`: the connection failing, or the indexer's REST
  (a backfill) rate limiting or failing on its side. A rejected request is not
  transient."""
  return isinstance(e, (NetworkError, RateLimited)) or type(e) is ApiError


Unsubscribe = Callable[[], Awaitable[object]]
Opened = tuple[AsyncIterator[T], Unsubscribe]
"""A channel's items and how to release it."""


@dataclass(frozen=True)
class Dropped:
  """The channel's connection dropped; it is reconnecting."""

  error: NetworkError


@dataclass(frozen=True)
class Reconnected:
  """The channel is open again; the reopened channel's items follow."""

  after: float
  """Seconds it was down."""


def reconnecting(
  name: str, open: Callable[[bool], Awaitable[Opened[T]]]
) -> Callable[[], Awaitable[Opened[T | Dropped | Reconnected]]]:
  """A `Subscription.of` callback whose channel reopens when its connection drops.

  The first open's errors are raised as they are. Afterwards, when the items fail with
  `NetworkError` or end, `Dropped` is yielded and the channel is released and reopened
  with exponential backoff (retrying `transient` errors); `Reconnected` is yielded and
  the items go on from the reopened channel. Only when it stays down for
  `GIVE_UP_AFTER` seconds is the last error raised, ending every subscriber still
  there. Other errors end it at once.

  Args:
    name: The channel, for logs.
    open: Opens the channel; its argument says whether this reopens after a drop.
  """

  async def subscribe() -> Opened[T | Dropped | Reconnected]:
    """Open the channel and keep it open."""
    items, release = await open(False)
    current: list[Unsubscribe] = [release]

    async def reopened() -> AsyncIterator[T | Dropped | Reconnected]:
      """The channel's items, across reconnections."""
      nonlocal items
      loop = asyncio.get_running_loop()
      while True:
        try:
          async for item in items:
            yield item
          error = NetworkError(f'dYdX indexer {name} ended')
        except NetworkError as e:
          error = e
        down = loop.time()
        log.warning('dYdX indexer %s dropped: %s; reconnecting', name, error)
        yield Dropped(error)
        with suppress(Exception):
          await current[0]()
        delay = RECONNECT_MIN
        while True:
          try:
            items, current[0] = await open(True)
            break
          except Exception as e:
            if not transient(e):
              raise
            if loop.time() - down + delay > GIVE_UP_AFTER:
              log.error('dYdX indexer %s still down after %.0fs', name, GIVE_UP_AFTER)
              raise
            log.warning(
              'dYdX indexer %s reconnect failed: %s; retrying in %.1fs', name, e, delay
            )
          await asyncio.sleep(delay)
          delay = min(delay * 2, RECONNECT_MAX)
        after = loop.time() - down
        log.warning('dYdX indexer %s reconnected after %.1fs', name, after)
        yield Reconnected(after)

    async def unsubscribe():
      """Release the channel open now."""
      await current[0]()

    return reopened(), unsubscribe

  return subscribe


def without_signals(
  subscribe: Callable[[], Awaitable[Opened[T | Dropped | Reconnected]]],
) -> Callable[[], Awaitable[Opened[T]]]:
  """A `reconnecting` callback whose subscribers see only the channel's items, a
  reconnection as a gap."""

  async def items_only() -> Opened[T]:
    """Open the channel, dropping `Dropped` and `Reconnected`."""
    items, unsubscribe = await subscribe()

    async def filtered() -> AsyncIterator[T]:
      async for item in items:
        if not isinstance(item, (Dropped, Reconnected)):
          yield item

    return filtered(), unsubscribe

  return items_only
