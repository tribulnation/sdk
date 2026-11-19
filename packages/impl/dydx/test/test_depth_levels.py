"""`levels` is an upper bound on dYdX's full Indexer book, REST and streamed."""

from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace

import pytest
from typing_extensions import Any, cast

from tribulnation.dydx.market.market import Market
from tribulnation.sdk.market import Book


def levels(n: int, start: int, step: int) -> list[dict[str, str]]:
  """`n` Indexer levels of one unit, best first."""
  return [{'price': str(start + step * i), 'size': '1'} for i in range(n)]


@pytest.mark.parametrize(('requested', 'served'), [(3, 3), (100, 100), (10**6, 100)])
async def test_depth_serves_at_most_levels(requested: int, served: int):
  """The Indexer answers its whole book; `levels` trims it and never refuses."""

  async def get_order_book(market: str) -> Any:
    """A 100-level book a side."""
    return {'bids': levels(100, 99, -1), 'asks': levels(100, 101, 1)}

  market = SimpleNamespace(
    market='BTC-USD',
    indexer=SimpleNamespace(data=SimpleNamespace(get_order_book=get_order_book)),
  )
  book = await Market.depth(cast(Market, market), levels=requested)
  assert len(book.bids) == len(book.asks) == served


@pytest.mark.parametrize(('requested', 'served'), [(3, 3), (100, 100), (10**6, 100)])
async def test_stream_serves_at_most_levels_from_a_detached_copy(
  requested: int, served: int
):
  """Each subscriber reads its own copy of the shared book, trimmed to `levels`."""
  shared = Book(
    bids=[Book.Entry(Decimal(99 - i), Decimal(1)) for i in range(100)],
    asks=[Book.Entry(Decimal(101 + i), Decimal(1)) for i in range(100)],
  )

  @asynccontextmanager
  async def subscribe_depth(market: str, **_: Any):
    """The shared, venue-mutated book."""

    async def books():
      """Yield the shared book once."""
      yield shared

    yield books()

  market = SimpleNamespace(market='BTC-USD', subscribe_depth=subscribe_depth)
  async with Market.depth_stream(cast(Market, market), levels=requested) as stream:
    book = await anext(aiter(stream))
  assert len(book.bids) == len(book.asks) == served
  assert book is not shared and book.bids[0] is not shared.bids[0]
