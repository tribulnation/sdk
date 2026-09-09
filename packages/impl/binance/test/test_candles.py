"""USD-M candles use the typed pager with native ordering and half-open filtering."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from typed_binance import Binance
from typed_binance.usdm_futures.http.market.klines import Klines

from tribulnation.binance.market.impl.mixin import Shared
from tribulnation.binance.market.perp_market import PerpMarket

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
MINUTE = timedelta(minutes=1)


async def test_usdm_bounds_and_native_order(monkeypatch: pytest.MonkeyPatch):
  """Nonascending row order passes through unchanged and out-of-range opens disappear."""

  def row(index: int):
    """One validated twelve-column USD-M kline."""
    time = START + index * MINUTE
    return (
      time,
      Decimal(1),
      Decimal(2),
      Decimal(1),
      Decimal(2),
      Decimal(3),
      time,
      Decimal(4),
      5,
      Decimal(1),
      Decimal(2),
      Decimal(0),
    )

  request = AsyncMock(return_value=[row(2), row(0), row(3), row(-1), row(1)])
  monkeypatch.setattr(Klines, 'klines', request)
  market = PerpMarket(shared=Shared(client=Binance.new(public=True)), symbol='BTCUSDT')
  candles = await market.candles('1m', START, START + 3 * MINUTE)
  assert [c.time for c in candles] == [row(2)[0], START, row(1)[0]]
  assert candles[0].quote_volume == Decimal(4)
  assert candles[0].trades == 5


async def test_empty_range_makes_no_request(monkeypatch: pytest.MonkeyPatch):
  """Equal bounds must avoid a venue request."""
  request = AsyncMock()
  monkeypatch.setattr(Klines, 'klines', request)
  market = PerpMarket(shared=Shared(client=Binance.new(public=True)), symbol='BTCUSDT')
  assert await market.candles('1m', START, START) == []
  request.assert_not_awaited()
