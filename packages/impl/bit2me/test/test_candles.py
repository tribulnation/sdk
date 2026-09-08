"""Sparse Bit2Me candle windows must not end the requested history early."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing_extensions import cast
from unittest.mock import AsyncMock

import pytest
from typed_bit2me import Bit2Me
from typed_bit2me.v1.trading.candles import Candles

from tribulnation.bit2me.core import Calls
from tribulnation.bit2me.market.impl.candles import candles
from tribulnation.bit2me.market.impl.mixin import MarketMixin

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
MINUTE = timedelta(minutes=1)


async def test_empty_window_does_not_hide_later_candles(
  monkeypatch: pytest.MonkeyPatch,
):
  """Walk past a wholly empty slot window, retaining native order and exact bounds."""

  def row(index: int):
    """One validated row with JSON-number prices."""
    return (START + index * MINUTE, 1.1, 2.2, 1.0, 2.0, 3.0)

  request = AsyncMock(side_effect=[[], [row(1000), row(999), row(998), row(997)]])
  monkeypatch.setattr(Candles, 'candles', request)
  market = cast(
    MarketMixin,
    SimpleNamespace(
      client=Bit2Me.new(public=True),
      symbol='B2M/EUR',
      call_bit2me=Calls().call_bit2me,
    ),
  )
  pages = [page async for page in candles(market, '1m', START, START + 1000 * MINUTE)]
  assert [[c.time for c in page] for page in pages] == [[row(999)[0], row(998)[0]]]
  assert pages[0][0].open == Decimal('1.1')
  assert request.await_count == 2
  assert request.await_args_list[1].kwargs['start_time'] == row(997)[0]


async def test_empty_range_does_not_fetch():
  """Equal bounds produce no windows or endpoint access."""
  market = cast(MarketMixin, SimpleNamespace())
  assert [page async for page in candles(market, '1m', START, START)] == []
