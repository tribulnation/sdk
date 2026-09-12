"""Bounded Coinbase windows preserve native row order and exclude overlapping opens."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from typed_coinbase import Coinbase
from typed_coinbase.app.advanced_trade.http.products.public.candles import Candles
from typed_coinbase.schemas import Candle

from tribulnation.coinbase.core.mixin import Shared
from tribulnation.coinbase.market import SpotMarket

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
MINUTE = timedelta(minutes=1)


def row(index: int) -> Candle:
  """Build a validated Coinbase candle."""
  return {
    'start': START + index * MINUTE,
    'open': Decimal(1),
    'high': Decimal(2),
    'low': Decimal(1),
    'close': Decimal(2),
    'volume': Decimal(3),
  }


async def test_windows_preserve_native_order_and_do_not_duplicate(
  monkeypatch: pytest.MonkeyPatch,
):
  """An end bucket shared by adjacent windows belongs only to the second window."""
  request = AsyncMock(
    side_effect=[
      {'candles': [row(299), row(298), row(0)]},
      {'candles': [row(301), row(300), row(299), row(298)]},
    ]
  )
  monkeypatch.setattr(Candles, 'candles', request)
  market = SpotMarket(
    shared=Shared(client=Coinbase.new(public=True)), product_id='BTC-USD'
  )
  pages = [page async for page in market.candles('1m', START, START + 301 * MINUTE)]
  assert [[c.time for c in page] for page in pages] == [
    [row(298)['start'], START],
    [row(300)['start'], row(299)['start']],
  ]
  assert request.await_count == 2
  assert request.await_args_list[1].kwargs['start'] == row(299)['start']


async def test_subsecond_end_keeps_the_last_open(monkeypatch: pytest.MonkeyPatch):
  """Wire rounding cannot exclude an opening before a fractional-second end."""
  request = AsyncMock(return_value={'candles': [row(1), row(0)]})
  monkeypatch.setattr(Candles, 'candles', request)
  market = SpotMarket(
    shared=Shared(client=Coinbase.new(public=True)), product_id='BTC-USD'
  )
  end = START + MINUTE + timedelta(microseconds=1)
  assert [c.time for c in await market.candles('1m', START, end)] == [
    row(1)['start'],
    START,
  ]
  assert request.await_args is not None
  assert request.await_args.kwargs['end'] > row(1)['start'] + timedelta(seconds=1)
