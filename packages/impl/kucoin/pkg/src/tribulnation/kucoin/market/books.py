"""Public depth snapshots and shared five-level WebSocket snapshots."""

from contextlib import asynccontextmanager
from decimal import Decimal
from typing_extensions import AsyncIterable, AsyncIterator

from tribulnation.sdk.core import OverflowPolicy, Subscription, exception_wrapper
from tribulnation.sdk.market import Book
from .common import Shared


def check_levels(levels: int | None, *, maximum: int):
  """Reject requests beyond the qualified public book depth."""
  if levels is not None and not 1 <= levels <= maximum:
    raise ValueError(f'KuCoin supports between 1 and {maximum} levels for this read')


async def depth(
  shared: Shared,
  exchange: str,
  symbol: str,
  multiplier: Decimal,
  *,
  levels: int | None = None,
) -> Book:
  """Read public partial books; linear perpetual sizes are contract lots."""
  check_levels(levels, maximum=100)
  size = '100' if levels is not None and levels > 20 else '20'
  if exchange == 'spot':
    raw = await shared.call(
      lambda: shared.client.spot.part_orderbook(size, symbol=symbol)
    )
    book = Book(
      bids=[Book.Entry(p, q) for p, q in raw['bids']],
      asks=[Book.Entry(p, q) for p, q in raw['asks']],
    )
  else:
    raw_perp = await shared.call(
      lambda: shared.client.futures.part_orderbook(size, symbol=symbol)
    )
    book = Book(
      bids=[
        Book.Entry(Decimal(str(p)), Decimal(q) * multiplier)
        for p, q in raw_perp['bids']
      ],
      asks=[
        Book.Entry(Decimal(str(p)), Decimal(q) * multiplier)
        for p, q in raw_perp['asks']
      ],
    )
  return book if levels is None else book.limit(levels)


def subscription(
  shared: Shared, exchange: str, symbol: str, multiplier: Decimal
) -> Subscription[Book]:
  """Reuse one five-level upstream per exchange and symbol."""
  key = (exchange, symbol)
  if key not in shared.books:

    @exception_wrapper()
    async def connect() -> Subscription.Context[Book]:
      """Translate stream acquisition, iteration and unsubscribe failures."""
      if exchange == 'spot':
        stream = await shared.client.streams.spot_margin_public.orderbook_level5(symbol)

        @exception_wrapper()
        async def spot_books() -> AsyncIterator[Book]:
          """Each push replaces the complete five-level snapshot."""
          async for row in stream:
            yield Book(
              bids=[Book.Entry(p, q) for p, q in row['bids']],
              asks=[Book.Entry(p, q) for p, q in row['asks']],
            )

        return Subscription.Context(
          spot_books(), exception_wrapper()(stream.unsubscribe)
        )
      stream_perp = await shared.client.streams.futures_public.orderbook_level5(symbol)

      @exception_wrapper()
      async def perp_books() -> AsyncIterator[Book]:
        """Convert contract lots on both sides into base quantities."""
        async for row in stream_perp:
          yield Book(
            bids=[Book.Entry(p, Decimal(q) * multiplier) for p, q in row['bids']],
            asks=[Book.Entry(p, Decimal(q) * multiplier) for p, q in row['asks']],
          )

      return Subscription.Context(
        perp_books(), exception_wrapper()(stream_perp.unsubscribe)
      )

    shared.books[key] = Subscription(connect)
  return shared.books[key]


@asynccontextmanager
async def depth_stream(
  shared: Shared,
  exchange: str,
  symbol: str,
  multiplier: Decimal,
  *,
  levels: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
):
  """Fan out a snapshot feed with the SDK's bounded per-subscriber queues."""
  check_levels(levels, maximum=5)
  source = subscription(shared, exchange, symbol, multiplier)

  async def trimmed(books: AsyncIterable[Book]) -> AsyncIterator[Book]:
    """Give every subscriber its own book, trimmed to its requested depth."""
    async for book in books:
      yield book.copy() if levels is None else book.limit(levels)

  async with source.subscribe(queue_size=queue_size, overflow=overflow) as stream:
    yield trimmed(stream)
