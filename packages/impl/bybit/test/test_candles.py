"""Candle bounds and lazy native ordering through the real Bybit pager."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from typed_bybit import Bybit
from typed_bybit.market.kline import Kline

from tribulnation.bybit.market import SpotMarket
from tribulnation.bybit.market.impl.history import KlineRow

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
MINUTE = timedelta(minutes=1)


def row(index: int) -> KlineRow:
  """Build a validated response row at a known opening time."""
  return (START + index * MINUTE, '1', '2', '1', '2', '3', '4')


async def test_native_pages_are_lazy_unique_and_half_open(
  monkeypatch: pytest.MonkeyPatch,
):
  """Yield newest-first immediately, dropping the exclusive end and repeated boundary."""
  request = AsyncMock(
    side_effect=[
      {
        'category': 'spot',
        'symbol': 'BTCUSDT',
        'list': [row(i) for i in range(1000, 0, -1)],
      },
      {'category': 'spot', 'symbol': 'BTCUSDT', 'list': [row(1), row(0), row(-1)]},
    ]
  )
  monkeypatch.setattr(Kline, 'kline', request)
  market = SpotMarket(client=Bybit.new(public=True), symbol='BTCUSDT')
  pages = aiter(market.candles('1m', START, START + 1000 * MINUTE))
  first = await anext(pages)
  assert [c.time for c in first] == [row(i)[0] for i in range(999, 0, -1)]
  assert request.await_count == 1
  rest = [page async for page in pages]
  assert [[c.time for c in page] for page in rest] == [[START]]
  assert request.await_count == 2
  assert request.await_args_list[1].kwargs['end'] == row(1)[0]


async def test_empty_range_makes_no_request(monkeypatch: pytest.MonkeyPatch):
  """Equal bounds are empty without contacting the venue."""
  request = AsyncMock()
  monkeypatch.setattr(Kline, 'kline', request)
  market = SpotMarket(client=Bybit.new(public=True), symbol='BTCUSDT')
  assert await market.candles('1m', START, START) == []
  request.assert_not_awaited()
