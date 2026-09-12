"""Half-open candle bounds and native pagination through the indexer's real pager."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing_extensions import Awaitable, Callable, TypeVar, cast
from unittest.mock import AsyncMock

import pytest
from typed_dydx import Dydx
from typed_dydx.indexer.data.get_candles import GetCandles
from typed_dydx.indexer.schemas import Candle

from tribulnation.dydx.market.impl.candles import candles
from tribulnation.dydx.market.impl.mixin import MarketMixin

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
MINUTE = timedelta(minutes=1)
T = TypeVar('T')


def row(index: int) -> Candle:
  """Build a validated indexer candle with distinct opening time."""
  return {
    'startedAt': START + index * MINUTE,
    'ticker': 'BTC-USD',
    'resolution': '1MIN',
    'open': Decimal(1),
    'high': Decimal(2),
    'low': Decimal(1),
    'close': Decimal(2),
    'baseTokenVolume': Decimal(3),
    'usdVolume': Decimal(4),
    'trades': 5,
    'startingOpenInterest': Decimal(6),
    'orderbookMidPriceClose': Decimal(2),
  }


async def call(fn: Callable[[], Awaitable[T]]) -> T:
  """Execute one already-mocked request."""
  return await fn()


async def test_native_pages_are_lazy_unique_and_half_open(
  monkeypatch: pytest.MonkeyPatch,
):
  """No full-history buffering or reversal; overlapping endpoint bounds are trimmed."""
  request = AsyncMock(
    side_effect=[
      {'candles': [row(i) for i in range(1000, 0, -1)]},
      {'candles': [row(1), row(0), row(-1)]},
    ]
  )
  monkeypatch.setattr(GetCandles, 'get_candles', request)
  market = cast(
    MarketMixin,
    SimpleNamespace(
      indexer=Dydx.mainnet(public=True).indexer,
      market='BTC-USD',
      call_dydx=call,
    ),
  )
  pages = aiter(candles(market, '1m', START, START + 1000 * MINUTE))
  first = await anext(pages)
  assert [c.time for c in first] == [row(i)['startedAt'] for i in range(999, 0, -1)]
  assert request.await_count == 1
  assert [[c.time for c in page] async for page in pages] == [[START]]
  assert request.await_count == 2


async def test_empty_range_makes_no_request(monkeypatch: pytest.MonkeyPatch):
  """Equal bounds avoid contacting the indexer."""
  request = AsyncMock()
  monkeypatch.setattr(GetCandles, 'get_candles', request)
  market = cast(MarketMixin, SimpleNamespace())
  assert [page async for page in candles(market, '1m', START, START)] == []
  request.assert_not_awaited()
