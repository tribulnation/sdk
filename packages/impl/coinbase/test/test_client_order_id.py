"""Client order IDs reach Advanced Trade, and fills name the order they executed."""

from typing_extensions import cast
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest
from typed_coinbase.app.advanced_trade.http.orders.create import CreateOrderSuccess
from typed_coinbase.app.advanced_trade.http.orders.historical.fills import Fill

from tribulnation.coinbase.market.impl.mixin import MarketMixin
from tribulnation.coinbase.market.impl.orders import place_order
from tribulnation.coinbase.market.impl.trades import parse_fill
from tribulnation.sdk.market import Order

TIME = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def market(create: AsyncMock) -> MarketMixin:
  """A product whose only endpoint is the given order creation."""
  orders = SimpleNamespace(create=create)
  app = SimpleNamespace(
    advanced_trade=SimpleNamespace(http=SimpleNamespace(orders=orders))
  )
  return cast(MarketMixin, SimpleNamespace(product_id='BTC-USD', app=app))


def created(client_order_id: str) -> CreateOrderSuccess:
  """A successful creation echoing the client order id."""
  return {
    'success': True,
    'success_response': {'order_id': 'o-1', 'client_order_id': client_order_id},
  }


@pytest.mark.parametrize('order_type', ['LIMIT', 'POST_ONLY', 'MARKET'])
async def test_place_order_sends_the_callers_client_order_id(order_type: str):
  """The caller's id replaces the generated one, unchanged."""
  create = AsyncMock(return_value=created('hedge-42'))
  order = cast(
    Order,
    {'type': order_type, 'qty': 1, 'price': 100, 'client_order_id': 'hedge-42'},
  )
  response = await place_order(market(create), order)
  assert response.id == 'o-1'
  assert create.await_args is not None
  assert create.await_args.kwargs['client_order_id'] == 'hedge-42'


async def test_place_order_generates_a_client_order_id_when_none_is_given():
  """Advanced Trade requires one, so each order without it gets a fresh UUID."""
  create = AsyncMock(return_value=created('generated'))
  order: Order = {'type': 'LIMIT', 'qty': 1, 'price': 100}
  await place_order(market(create), order)
  await place_order(market(create), order)
  sent = [call.kwargs['client_order_id'] for call in create.await_args_list]
  assert len({uuid.UUID(value) for value in sent}) == 2


def test_history_fills_name_their_order_but_not_its_client_id():
  """`Fill` rows carry `order_id` only; the client id lives on the order."""
  fill: Fill = {
    'entry_id': 'e-1',
    'trade_id': 't-1',
    'order_id': 'o-1',
    'trade_time': TIME,
    'trade_type': 'FILL',
    'price': Decimal('100'),
    'size': Decimal('0.5'),
    'commission': Decimal('0.1'),
    'product_id': 'BTC-USD',
    'sequence_timestamp': TIME,
    'liquidity_indicator': 'MAKER',
    'size_in_quote': False,
    'user_id': 'u-1',
    'side': 'SELL',
  }
  trade = parse_fill(fill, quote='USD')
  assert (trade.id, trade.order_id, trade.client_order_id) == ('t-1', 'o-1', None)
  assert trade.qty == Decimal('-0.5')
