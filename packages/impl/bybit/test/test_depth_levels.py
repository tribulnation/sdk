"""`levels` is an upper bound on the shared Bybit book stream."""

from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace

import pytest
from typing_extensions import Any, cast

from tribulnation.bybit.market.impl.mixin import MarketMixin
from tribulnation.bybit.market.impl.streams import depth_stream
from tribulnation.sdk.market import Book


def book(n: int) -> Book:
  """`n` levels of one unit a side."""
  return Book(
    bids=[Book.Entry(Decimal(99 - i), Decimal(1)) for i in range(n)],
    asks=[Book.Entry(Decimal(101 + i), Decimal(1)) for i in range(n)],
  )


@pytest.mark.parametrize(('levels', 'served'), [(3, 3), (50, 50), (10**6, 50)])
async def test_stream_serves_at_most_levels(levels: int, served: int):
  """The 50-level feed is trimmed to `levels`; above it, the whole feed is served."""

  @asynccontextmanager
  async def subscribe_depth(**_: Any):
    """One shared 50-level book."""

    async def books():
      """Yield the book once."""
      yield book(50).frozen()

    yield books()

  market = cast(MarketMixin, SimpleNamespace(subscribe_depth=subscribe_depth))
  async with depth_stream(market, levels=levels) as stream:
    first = await anext(aiter(stream))
  assert len(first.bids) == len(first.asks) == served
