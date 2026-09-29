"""Client order IDs reach spot orders, and fills name the order they executed."""

from typing_extensions import Any, AsyncIterator, cast
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import re

import pytest
from typed_mexc.spot.http.account.trades import AccountTrade
from typed_mexc.spot.streams.core.proto import PrivateDealsV3Api

from tribulnation.mexc.market import SpotMarket
from tribulnation.mexc.market.impl.mixin import MarketMixin
from tribulnation.mexc.market.impl.orders import _dump_order
from tribulnation.mexc.market.impl.trades import _parse_trade, trades_stream
from tribulnation.sdk.market import Order

TIME = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize('order_type', ['LIMIT', 'POST_ONLY', 'MARKET'])
@pytest.mark.parametrize('client_order_id', ['hedge-42', None])
def test_dump_order_sends_client_order_id_only_when_given(
  order_type: str, client_order_id: str | None
):
  """`newClientOrderId` carries the caller's id unchanged, and is absent otherwise."""
  order = cast(Order, {'type': order_type, 'qty': '-0.5', 'price': '100'})
  order['client_order_id'] = client_order_id
  request = _dump_order('BTCUSDT', order, recv_window=None)
  assert request.get('newClientOrderId') == client_order_id
  assert (request['side'], request['quantity']) == ('SELL', Decimal('0.5'))


@pytest.mark.parametrize('client_order_id', ['hedge-42', None, ''])
def test_history_fills_name_their_order_and_client_id(client_order_id: str | None):
  """`myTrades` rows carry `orderId` and a nullable `clientOrderId`."""
  row: AccountTrade = {
    'symbol': 'BTCUSDT',
    'id': 'f-1',
    'orderId': 'C02__443776347957968896',
    'orderListId': -1,
    'price': Decimal('100'),
    'qty': Decimal('0.5'),
    'quoteQty': Decimal('50'),
    'commission': Decimal('0.05'),
    'commissionAsset': 'USDT',
    'time': TIME,
    'isBuyer': True,
    'isMaker': False,
    'isBestMatch': True,
    'isSelfTrade': False,
    'clientOrderId': client_order_id,
  }
  trade = _parse_trade(row)
  assert trade.order_id == 'C02__443776347957968896'
  assert trade.client_order_id == (client_order_id or None)


async def test_streamed_fills_name_their_order_and_client_id():
  """Pushed deals carry both ids; the empty strings of unset fields become none."""
  tagged = PrivateDealsV3Api(
    price='100',
    quantity='0.5',
    trade_type=2,
    trade_id='d-1',
    client_order_id='hedge-42',
    order_id='C02__443776347957968896',
    fee_amount='0.05',
    fee_currency='USDT',
    time=1788523200000,
  )
  untagged = PrivateDealsV3Api(
    price='100',
    quantity='0.5',
    trade_type=1,
    trade_id='d-2',
    fee_amount='0.05',
    fee_currency='USDT',
    time=1788523200000,
  )

  @asynccontextmanager
  async def subscribe_my_trades(**_: Any) -> AsyncIterator[AsyncIterator[Any]]:
    """Replay the fixture deals as one subscription."""

    async def messages() -> AsyncIterator[Any]:
      """The deals, with an unrelated message in between."""
      yield tagged
      yield object()
      yield untagged

    yield messages()

  market = cast(MarketMixin, SimpleNamespace(subscribe_my_trades=subscribe_my_trades))
  async with trades_stream(market) as stream:
    rows = [trade async for trade in stream]
  assert [(t.id, t.order_id, t.client_order_id) for t in rows] == [
    ('d-1', 'C02__443776347957968896', 'hedge-42'),
    ('d-2', None, None),
  ]
  assert rows[0].qty == Decimal('-0.5')


def test_client_order_id_generates_hex():
  """Fresh `newClientOrderId`s are 32 hex digits; the generator reads no market state."""
  market = object.__new__(SpotMarket)
  ids = {market.client_order_id() for _ in range(100)}
  assert len(ids) == 100
  assert all(re.fullmatch(r'[0-9a-f]{32}', value) for value in ids)
