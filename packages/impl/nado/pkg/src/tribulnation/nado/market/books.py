"""Order books: REST snapshots of up to 100 levels per side, and one shared stream per
product maintaining the book from a snapshot and the `book_depth` diffs."""

from contextlib import asynccontextmanager
from datetime import datetime

from typing_extensions import AsyncIterator, Sequence
from typed_nado.gateway.market_liquidity import MarketLiquidity
from typed_nado.streams.book_depth import BookDepthEvent
from tribulnation.sdk.core import NetworkError, OverflowPolicy, Subscription
from tribulnation.sdk.market import Book, detached_books

from ..core import Shared, wrap_exceptions, x18

MAX_LEVELS = 100
"""The most levels per side `market_liquidity` returns."""


def entries(levels: Sequence[tuple[int, int]]) -> list[Book.Entry]:
  """Book entries from venue `[price_x18, size_x18]` levels."""
  return [Book.Entry(x18(price), x18(size)) for price, size in levels]


def parse_book(raw: MarketLiquidity) -> Book:
  """A snapshot, timed by its `timestamp`."""
  return Book(
    bids=entries(raw['bids']), asks=entries(raw['asks']), time=raw['timestamp']
  )


def venue_depth(levels: int | None) -> int:
  """The levels to request: `levels`, capped at the venue's 100."""
  return MAX_LEVELS if levels is None else max(1, min(levels, MAX_LEVELS))


async def snapshot(shared: Shared, product_id: int, depth: int) -> MarketLiquidity:
  """One `market_liquidity` snapshot."""
  return await shared.call(
    lambda: shared.client.gateway.market_liquidity(product_id=product_id, depth=depth)
  )


async def depth(shared: Shared, product_id: int, *, levels: int | None = None) -> Book:
  """The aggregated book, at most 100 levels per side (all 100 when `levels` is
  `None`)."""
  book = parse_book(await snapshot(shared, product_id, venue_depth(levels)))
  return book if levels is None else book.limit(levels)


def chains(diff: BookDepthEvent, last: datetime | None, snapshot: datetime) -> bool:
  """Whether `diff` follows the last diff applied, or, before any, the snapshot.

  The first diff past the snapshot must follow one the snapshot already holds (ending
  at or before its `timestamp`); one following a diff ending later means the diff that
  bridged the snapshot was lost.
  """
  if last is None:
    return diff['last_max_timestamp'] <= snapshot
  else:
    return diff['last_max_timestamp'] == last


def subscription(shared: Shared, product_id: int) -> Subscription[Book]:
  """One upstream per product: a 100-level snapshot, then the `book_depth` diffs.

  The stream is subscribed first and the snapshot read after; diffs whose
  `max_timestamp` is not past the snapshot's `timestamp` are already in it and are
  dropped, and every later one is applied (sizes are absolute, `0` deletes the level).
  Each diff names the previous one's `max_timestamp` as its `last_max_timestamp`; a
  diff that does not chain onto the last one applied, or a first one that does not
  follow a diff the snapshot holds, ends the stream with `NetworkError` (a lost diff). Verified on BTC-PERP (2026-11-17): applying the diffs
  between two snapshots reproduced the second snapshot's top 10 levels exactly.

  The snapshot holds 100 levels per side, so levels deeper than that are known only
  once a diff touches them, and the book is trimmed to 100 levels per side.
  """
  if product_id not in shared.books:

    @wrap_exceptions
    async def connect() -> Subscription.Context[Book]:
      """Subscribe, then read the snapshot the diffs are applied to."""
      stream = await shared.client.streams.book_depth(product_id)

      @wrap_exceptions
      async def books() -> AsyncIterator[Book]:
        """Apply each diff past the snapshot; yield the book after each one."""
        raw = await snapshot(shared, product_id, MAX_LEVELS)
        book = parse_book(raw)
        last = None
        yield book.limit(MAX_LEVELS)
        async for diff in stream:
          if diff['max_timestamp'] <= raw['timestamp']:
            continue
          if not chains(diff, last, raw['timestamp']):
            after = raw['timestamp'] if last is None else last
            raise NetworkError(
              f'Nado book_depth diff lost on product {product_id}: expected one after '
              f'{after.isoformat()}, got one after {diff["last_max_timestamp"].isoformat()}'
            )
          last = diff['max_timestamp']
          book.update(
            Book(
              bids=entries(diff['bids']),
              asks=entries(diff['asks']),
              time=diff['max_timestamp'],
            )
          )
          yield book.limit(MAX_LEVELS)

      return Subscription.Context(books(), wrap_exceptions(stream.unsubscribe))

    shared.books[product_id] = Subscription(connect)
  return shared.books[product_id]


@asynccontextmanager
async def depth_stream(
  shared: Shared,
  product_id: int,
  *,
  levels: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
):
  """Fan out the shared book; each subscriber gets its own copy, trimmed to `levels`.

  Args:
    shared: The owner of the client and its fan-outs.
    product_id: The product.
    levels: Keep at most this many levels per side.
    queue_size: Books buffered for this subscriber.
    overflow: What to do when the buffer is full.
  """
  upstream = subscription(shared, product_id)
  async with upstream.subscribe(queue_size=queue_size, overflow=overflow) as stream:
    yield detached_books(stream, levels)
