"""`levels` is an upper bound on Kraken spot REST depth, which tops out at 500."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from typing_extensions import Any, cast

from tribulnation.kraken.market.impl.depth import book_depth, depth, rest_count
from tribulnation.kraken.market.impl.mixin import MarketMixin


def test_rest_count_caps_at_the_deepest_book():
  """Above 500 Kraken would answer its 100-level default, so the count stops at 500."""
  assert rest_count(None) is None
  assert rest_count(3) == 3
  assert rest_count(500) == rest_count(501) == rest_count(10**6) == 500


def test_stream_depth_caps_at_the_deepest_channel():
  """Above 1000 levels the `book` channel subscribes at 1000 rather than failing."""
  assert book_depth(1001) == book_depth(10**6) == 1000


@pytest.mark.parametrize(('levels', 'count'), [(3, 3), (501, 500), (10**6, 500)])
async def test_depth_requests_at_most_500(levels: int, count: int):
  """The REST read is sent the capped count and returns what Kraken serves."""
  counts: list[int | None] = []

  async def call_kraken(fn: Any) -> Any:
    """Run the request."""
    return await fn()

  async def rest_depth(pair: str, *, count: int | None = None) -> Any:
    """Answer `count` levels a side, keyed by the pair's internal name."""
    counts.append(count)
    n = count or 100
    return {
      'XXBTZUSD': {
        'bids': [(Decimal(99 - i), Decimal(1), 0) for i in range(n)],
        'asks': [(Decimal(101 + i), Decimal(1), 0) for i in range(n)],
      }
    }

  market = SimpleNamespace(
    call_kraken=call_kraken,
    altname='XBTUSD',
    meta={'pair': {'key': 'XXBTZUSD'}},
    client=SimpleNamespace(
      spot=SimpleNamespace(market_data=SimpleNamespace(depth=rest_depth))
    ),
  )
  book = await depth(cast(MarketMixin, market), levels=levels)
  assert counts == [count]
  assert len(book.bids) == len(book.asks) == count
