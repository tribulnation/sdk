"""Spot fills carry the id of the order they executed and its client order id."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from typed_binance import Binance
from typed_binance.spot.http.account.my_trades import MyTrades, SpotTradeItem
from typed_binance.spot.ws.user_data.events import (
  Events,
  ExecutionReportEvent,
  UserDataPush,
)
from typed_core.util import Stream, StreamManager
from typing_extensions import AsyncIterator

from tribulnation.binance.market.impl.mixin import Shared
from tribulnation.binance.market.spot_market import SpotMarket

TIME = datetime(2026, 9, 9, tzinfo=timezone.utc)


def market() -> SpotMarket:
  """A spot market on a credential-free client; tests replace the endpoints."""
  return SpotMarket(shared=Shared(client=Binance.new(public=True)), symbol='BTCUSDT')


def my_trade() -> SpotTradeItem:
  """One decoded `myTrades` row."""
  return {
    'symbol': 'BTCUSDT',
    'id': 28457,
    'orderId': 100234,
    'orderListId': -1,
    'price': Decimal('4.00000100'),
    'qty': Decimal('12.00000000'),
    'quoteQty': Decimal('48.000012'),
    'commission': Decimal('10.10000000'),
    'commissionAsset': 'BNB',
    'time': TIME,
    'isBuyer': True,
    'isMaker': False,
    'isBestMatch': True,
  }


def execution_report(client_id: str) -> ExecutionReportEvent:
  """One decoded `executionReport` push for a partial fill."""
  return {
    'e': 'executionReport',
    'E': TIME,
    's': 'BTCUSDT',
    'c': client_id,
    'S': 'SELL',
    'o': 'LIMIT',
    'f': 'GTC',
    'q': Decimal('1.00000000'),
    'p': Decimal('0.10264410'),
    'P': Decimal('0'),
    'F': Decimal('0'),
    'g': -1,
    'C': '',
    'x': 'TRADE',
    'X': 'PARTIALLY_FILLED',
    'r': 'NONE',
    'i': 4293153,
    'l': Decimal('0.25000000'),
    'z': Decimal('0.25000000'),
    'L': Decimal('0.10264410'),
    'n': Decimal('0.00002566'),
    'N': 'USDT',
    'T': TIME,
    't': 1765,
    'v': 3,
    'I': 8641984,
    'w': True,
    'm': True,
    'M': False,
    'O': TIME,
    'Z': Decimal('0.02566102'),
    'Y': Decimal('0.02566102'),
    'Q': Decimal('0'),
    'W': TIME,
    'V': 'NONE',
  }


async def test_history_maps_order_id_without_client_id(
  monkeypatch: pytest.MonkeyPatch,
):
  """`myTrades` has the native order id but never the client order id."""
  monkeypatch.setattr(MyTrades, 'my_trades', AsyncMock(return_value=[my_trade()]))
  trades = await market().trades_history(TIME, TIME + timedelta(hours=1))
  assert [(t.id, t.order_id, t.client_order_id) for t in trades] == [
    ('28457', '100234', None)
  ]


@pytest.mark.parametrize(
  'client_id,expected',
  [('web_7f3c1a2b9d', 'web_7f3c1a2b9d'), ('', None)],
)
async def test_stream_maps_order_and_client_ids(
  monkeypatch: pytest.MonkeyPatch, client_id: str, expected: str | None
):
  """A fill push reports its order's `i` and `c`, with an empty `c` meaning none."""
  push: UserDataPush = {'subscriptionId': 0, 'event': execution_report(client_id)}

  async def pushes() -> AsyncIterator[UserDataPush]:
    """The single push this subscription delivers."""
    yield push

  def events(self: Events) -> StreamManager[UserDataPush]:
    """Connect to a local stream instead of the WS API."""
    stream = Stream(reply=None, stream=pushes(), unsubscribe=AsyncMock())
    return StreamManager(connect=AsyncMock(return_value=stream))

  monkeypatch.setattr(Events, 'events', events)
  async with market().trades_stream() as trades:
    trade = await anext(aiter(trades))
  assert trade.id == '1765'
  assert trade.order_id == '4293153'
  assert trade.client_order_id == expected
  assert trade.qty == Decimal('-0.25000000')
