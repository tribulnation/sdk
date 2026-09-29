"""Client order IDs reach the order request, and fills name the order they executed."""

from typing_extensions import cast
from datetime import datetime, timezone

import pytest
from typed_bit2me.schemas import TradeResponse
from typed_bit2me.trading_ws.my_trades import MyTradeUpdate

from tribulnation.bit2me.market.impl.orders import dump_order
from tribulnation.bit2me.market.impl.trades import parse_trade, parse_update
from tribulnation.sdk.market import Order

TIME = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
ORDER_ID = '0d9f8a3e-2b4c-4d6e-8f10-a1b2c3d4e5f6'


@pytest.mark.parametrize('order_type', ['LIMIT', 'POST_ONLY', 'MARKET'])
@pytest.mark.parametrize('client_order_id', ['hedge-42', None])
def test_dump_order_sends_client_order_id_only_when_given(
  order_type: str, client_order_id: str | None
):
  """`clientOrderId` carries the caller's id unchanged, and is absent otherwise."""
  order = cast(Order, {'type': order_type, 'qty': '-0.5', 'price': '100'})
  if client_order_id is not None:
    order['client_order_id'] = client_order_id
  request = dump_order('BTC/EUR', order)
  if client_order_id is None:
    assert 'clientOrderId' not in request
  else:
    assert request.get('clientOrderId') == client_order_id
  assert (request['side'], request['amount']) == ('sell', '0.5')


@pytest.mark.parametrize(
  'client_order_id,expected', [('hedge-42', 'hedge-42'), (None, None), ('', None)]
)
def test_history_fills_name_their_order_and_client_id(
  client_order_id: str | None, expected: str | None
):
  """`v1/trading/trade` rows carry `orderId` and a nullable `clientOrderId`."""
  row: TradeResponse = {
    'id': 't-1',
    'orderId': ORDER_ID,
    'symbol': 'BTC/EUR',
    'side': 'buy',
    'price': 100.0,
    'amount': 0.5,
    'isMaker': True,
    'createdAt': TIME,
    'clientOrderId': client_order_id,
  }
  trade = parse_trade(row)
  assert (trade.id, trade.order_id, trade.client_order_id) == (
    't-1',
    ORDER_ID,
    expected,
  )


def test_streamed_fills_name_their_order_and_client_id():
  """Pushed fills name the order as `order`; a missing client id is none."""
  update: MyTradeUpdate = {
    'id': 't-2',
    'symbol': 'BTC/EUR',
    'order': ORDER_ID,
    'side': 'sell',
    'price': 100.0,
    'amount': 0.5,
    'datetime': TIME,
    'clientOrderId': 'hedge-42',
  }
  trade = parse_update(update)
  assert (trade.order_id, trade.client_order_id) == (ORDER_ID, 'hedge-42')
  untagged = parse_update({**update, 'clientOrderId': None})
  assert untagged.client_order_id is None
  bare: MyTradeUpdate = {
    'id': 't-3',
    'symbol': 'BTC/EUR',
    'side': 'buy',
    'price': 100.0,
    'amount': 0.5,
  }
  assert (parse_update(bare).order_id, parse_update(bare).client_order_id) == (
    None,
    None,
  )
