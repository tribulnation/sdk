"""`levels` is an upper bound: margin.trade serves at most its 20-level `l2Book`."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from typed_margin_trade.schemas import L2Book

from tribulnation.margin_trade.core import parse_book


@pytest.mark.parametrize(('levels', 'served'), [(3, 3), (20, 20), (10**6, 20)])
def test_book_serves_at_most_levels(levels: int, served: int):
  """The snapshot is trimmed to `levels` and served whole above it."""
  raw: L2Book = {
    'coin': 'BTC',
    'time': datetime(2026, 11, 19, tzinfo=timezone.utc),
    'levels': [
      [{'px': Decimal(99 - i), 'sz': Decimal(1), 'n': 1} for i in range(20)],
      [{'px': Decimal(101 + i), 'sz': Decimal(1), 'n': 1} for i in range(20)],
    ],
  }
  book = parse_book(raw, levels)
  assert len(book.bids) == len(book.asks) == served
