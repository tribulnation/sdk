"""`levels` is an upper bound: RISEx's REST book is capped at 250 levels."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typing_extensions import Any, cast

from tribulnation.risex.core import Shared
from tribulnation.risex.market import books


@pytest.mark.parametrize(('levels', 'limit'), [(3, 3), (250, 250), (10**6, 250)])
async def test_depth_requests_at_most_250(levels: int, limit: int):
  """Above 250 the request asks for 250 and serves what the venue returns."""
  sent: list[int] = []

  async def call(fn: Any) -> Any:
    """Run the request."""
    return await fn()

  async def orderbook(*, market_id: int, limit: int) -> Any:
    """Answer `limit` levels a side."""
    sent.append(limit)
    return {
      'bids': [
        {'price': Decimal(99 - i), 'quantity': Decimal(1)} for i in range(limit)
      ],
      'asks': [
        {'price': Decimal(101 + i), 'quantity': Decimal(1)} for i in range(limit)
      ],
    }

  shared = SimpleNamespace(
    market=AsyncMock(),
    call=call,
    client=SimpleNamespace(markets=SimpleNamespace(orderbook=orderbook)),
  )
  book = await books.depth(cast(Shared, shared), 1, levels=levels)
  assert sent == [limit]
  assert len(book.bids) == len(book.asks) == limit
