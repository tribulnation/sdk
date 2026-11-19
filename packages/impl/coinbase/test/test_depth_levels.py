"""`levels` is an upper bound on Coinbase books, REST and streamed."""

from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace

import pytest
from typing_extensions import Any, cast

from tribulnation.coinbase.market.impl.depth import depth, depth_stream
from tribulnation.coinbase.market.impl.mixin import MarketMixin
from tribulnation.sdk.market import Book


@pytest.mark.parametrize(('levels', 'served'), [(3, 3), (1000, 1000), (10**6, 1000)])
async def test_depth_passes_levels_and_serves_the_venue_cap(levels: int, served: int):
  """The pricebook `limit` is sent as asked; Coinbase answers at most 1000 levels."""

  async def book(product_id: str, *, limit: int | None = None) -> Any:
    """Answer at most 1000 levels a side, as the venue does."""
    n = min(limit or 1000, 1000)
    return {
      'pricebook': {
        'bids': [{'price': Decimal(99 - i), 'size': Decimal(1)} for i in range(n)],
        'asks': [{'price': Decimal(101 + i), 'size': Decimal(1)} for i in range(n)],
      }
    }

  public = SimpleNamespace(book=book)
  app = SimpleNamespace(
    advanced_trade=SimpleNamespace(
      http=SimpleNamespace(products=SimpleNamespace(public=public))
    )
  )
  market = SimpleNamespace(app=app, product_id='BTC-USD')
  result = await depth(cast(MarketMixin, market), levels=levels)
  assert len(result.bids) == len(result.asks) == served


@pytest.mark.parametrize(('levels', 'served'), [(3, 3), (10**6, 40)])
async def test_stream_serves_at_most_levels(levels: int, served: int):
  """The folded `level2` book is trimmed to `levels` and served whole above it."""

  @asynccontextmanager
  async def subscribe_book(product_id: str, **_: Any):
    """One shared 40-level book."""

    async def books():
      """Yield the book once."""
      yield Book(
        bids=[Book.Entry(Decimal(99 - i), Decimal(1)) for i in range(40)],
        asks=[Book.Entry(Decimal(101 + i), Decimal(1)) for i in range(40)],
      ).frozen()

    yield books()

  market = SimpleNamespace(subscribe_book=subscribe_book, product_id='BTC-USD')
  async with depth_stream(cast(MarketMixin, market), levels=levels) as stream:
    first = await anext(aiter(stream))
  assert len(first.bids) == len(first.asks) == served
