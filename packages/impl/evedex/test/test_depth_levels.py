"""`levels` is an upper bound: EVEDEX serves at most its 100-level REST book."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typing_extensions import Any, cast

from tribulnation.evedex.core import Shared
from tribulnation.evedex.market import books


@pytest.mark.parametrize(('levels', 'served'), [(3, 3), (100, 100), (10**6, 100)])
async def test_depth_serves_at_most_levels(levels: int, served: int):
  """The whole 100-level book is trimmed to `levels`, never refused above it."""

  async def call(fn: Any) -> Any:
    """Run the request."""
    return await fn()

  async def order_book(*, instrument: str) -> Any:
    """A 100-level book a side."""
    return {
      'bids': [{'price': Decimal(99 - i), 'quantity': Decimal(1)} for i in range(100)],
      'asks': [{'price': Decimal(101 + i), 'quantity': Decimal(1)} for i in range(100)],
      't': None,
    }

  shared = SimpleNamespace(
    instrument=AsyncMock(),
    call=call,
    client=SimpleNamespace(
      exchange=SimpleNamespace(market=SimpleNamespace(order_book=order_book))
    ),
  )
  book = await books.depth(cast(Shared, shared), 'BTCUSD', levels=levels)
  assert len(book.bids) == len(book.asks) == served
