"""Order semantics and error translation through real SDK market adapters."""

from decimal import Decimal
from unittest.mock import AsyncMock
import pytest
from typed_aster import AuthError as ClientAuthError, BadRequest as ClientBadRequest
from typed_aster.futures.trade.place_order import PlaceOrder as PerpOrders
from typed_aster.spot.trade.place_order import PlaceOrder as SpotOrders
from typed_aster.futures.trade.order import Order as PerpQuery
from typed_aster.spot.trade.order import Order as SpotQuery
from typed_aster.futures.trade.cancel_batch_orders import CancelBatchOrders
from tribulnation.aster import AsterMarket
from tribulnation.sdk import AuthError, BadRequest
from tribulnation.sdk.market import Order
from typing_extensions import Literal


@pytest.mark.parametrize('scope', ['spot', 'perp'])
@pytest.mark.parametrize('kind', ['MARKET', 'LIMIT', 'POST_ONLY'])
@pytest.mark.parametrize('qty', [Decimal('12.34'), Decimal('-12.34')])
async def test_signed_order_types(
  scope: str,
  kind: Literal['MARKET', 'LIMIT', 'POST_ONLY'],
  qty: Decimal,
  monkeypatch: pytest.MonkeyPatch,
):
  """MARKET omits price/TIF; GTC and GTX preserve price, sign and native order ID."""
  endpoint = AsyncMock(return_value={'orderId': 123})
  monkeypatch.setattr(
    PerpOrders if scope == 'perp' else SpotOrders, 'place_order', endpoint
  )
  venue = AsterMarket.new(public=True, mainnet=False)
  exchange = venue.perp if scope == 'perp' else venue.spot
  order: Order = {'type': kind, 'qty': qty, 'price': '0.75'}
  placed = await exchange.place_order('ASTERUSDT', order)
  assert endpoint.await_args is not None
  request = endpoint.await_args.args[0]
  assert placed.id == '123'
  assert request['quantity'] == abs(qty)
  assert request['side'] == ('BUY' if qty > 0 else 'SELL')
  if kind == 'MARKET':
    assert 'price' not in request and 'timeInForce' not in request
  else:
    assert request['price'] == Decimal('0.75')
    assert request['timeInForce'] == ('GTX' if kind == 'POST_ONLY' else 'GTC')


@pytest.mark.parametrize('scope', ['spot', 'perp'])
async def test_only_documented_not_found_is_none(
  scope: str, monkeypatch: pytest.MonkeyPatch
):
  """Authentication and unrelated bad requests must remain SDK failures."""
  endpoint = AsyncMock(
    side_effect=[
      ClientBadRequest(400, {'code': -2013, 'msg': 'Order does not exist'}),
      ClientBadRequest(400, {'code': -1100, 'msg': 'Illegal parameter'}),
      ClientAuthError('invalid agent'),
    ]
  )
  monkeypatch.setattr(PerpQuery if scope == 'perp' else SpotQuery, 'order', endpoint)
  venue = AsterMarket.new(public=True, mainnet=False)
  exchange = venue.perp if scope == 'perp' else venue.spot
  assert await exchange.query_order('ASTERUSDT', '123') is None
  with pytest.raises(BadRequest):
    await exchange.query_order('ASTERUSDT', '123')
  with pytest.raises(AuthError):
    await exchange.query_order('ASTERUSDT', '123')


async def test_batch_boundary_retains_partial_errors(monkeypatch: pytest.MonkeyPatch):
  """The eleven-order path makes two requests and does not hide batch errors."""
  results = [{'orderId': n} for n in range(10)] + [
    {'code': -2011, 'msg': 'Unknown order'}
  ]
  endpoint = AsyncMock(side_effect=[results[:10], results[10:]])
  monkeypatch.setattr(CancelBatchOrders, 'cancel_batch_orders', endpoint)
  exchange = AsterMarket.new(public=True, mainnet=False).perp
  assert (
    await exchange.cancel_orders('ASTERUSDT', [str(n) for n in range(11)]) == results
  )
  assert [c.args[0]['orderIdList'] for c in endpoint.await_args_list] == [
    list(range(10)),
    [10],
  ]
  assert await exchange.cancel_orders('ASTERUSDT', []) == []
  assert endpoint.await_count == 2
