"""Order book, snapshot and stream."""

from typing_extensions import TYPE_CHECKING, Sequence
from contextlib import asynccontextmanager
from decimal import Decimal

from tribulnation.sdk.core import OverflowPolicy
from tribulnation.sdk.market import Book

from typed_bit2me.trading_ws.order_book import OrderBookUpdate

if TYPE_CHECKING:
  from .mixin import MarketMixin

Level = tuple[float, float] | tuple[float, float, float]


def parse_levels(rows: Sequence[Level]) -> list[Book.Entry]:
  """Read `[price, amount]` levels, by index.

  Most markets send two-element rows, but the thin and stablecoin pairs send
  `[price, amount, notional]` triples, so unpacking would fail on those.
  """
  return [
    Book.Entry(price=Decimal(str(row[0])), qty=Decimal(str(row[1]))) for row in rows
  ]


def parse_book(update: OrderBookUpdate) -> Book:
  """Map one streamed level-2 snapshot onto a `Book`."""
  return Book(
    bids=parse_levels(update['bids']),
    asks=parse_levels(update['asks']),
  )


async def depth(self: 'MarketMixin', *, levels: int | None = None) -> Book:
  """Fetch the market order book.

  `v2/trading/order-book` takes only `symbol`: a `limit`/`depth` query parameter is
  ignored rather than honoured, and the response is capped at 100 levels per side.
  So `levels` truncates the answer client-side.
  """
  raw = await self.call_bit2me(
    lambda: self.client.v2.trading.order_book(symbol=self.symbol)
  )
  bids = parse_levels(raw.get('bids') or [])
  asks = parse_levels(raw.get('asks') or [])
  if levels is not None:
    bids, asks = bids[:levels], asks[:levels]
  return Book(bids=bids, asks=asks)


@asynccontextmanager
async def depth_stream(
  self: 'MarketMixin',
  *,
  levels: int | None = None,
  queue_size: int = 1,
  overflow: OverflowPolicy = 'latest',
):
  """Subscribe to the market order book.

  `levels` is accepted for interface compatibility and does not size the streamed
  book: the channel sends whatever depth it sends. Use `depth(levels=...)` for a
  sized snapshot.
  """
  async with self.subscribe_depth(queue_size=queue_size, overflow=overflow) as stream:
    yield stream
